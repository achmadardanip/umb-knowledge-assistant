"""UMB answerability benchmark runner (two-tier).

Tier A — retrieval (all questions, fast, no LLM): answerability, retrieval
accuracy (expected-source hit), citation quality (archive/forbidden at rank 1),
coverage and latency, per category. This is the diagnostic that surfaces weak
knowledge domains.

Tier B — generation (optional, stratified sample): runs the answer generator on
the retrieved contexts and scores groundedness / hallucination / faithfulness
with the same offline entailment engine the live CGCV gate uses (no LLM judge
required). Bounded by ``--sample-per-category`` because local CPU generation is
slow; the retrieval tier already covers every question.

Per-question records follow the requested schema (answerable, grounded,
hallucinated, retrieved_sources, confidence, latency_ms) plus diagnostics.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.evaluation.benchmark_dataset import generate_benchmark, load_entities
from app.evaluation.evaluate_rag import _is_noisy, _target_match, _target_rank
from app.evaluation.metrics import faithfulness_score
from app.ingestion.embedder import get_embedder
from app.rag.intent_classifier import classify_intent
from app.retrieval.hybrid_retriever import HybridRetriever
from app.trust.authority import host_authority
from app.verification.entailment import LexicalEntailmentChecker

CONTROL_CATEGORIES = {"out_of_scope", "private_credential", "unanswerable"}
DEFAULT_DATASET = Path(__file__).with_name("umb_benchmark.json")

# Benchmark category -> the intent(s) detect_intent() should route it to (Batch 6
# intent-routing accuracy). A set allows acceptable near-synonyms.
_CATEGORY_EXPECTED_INTENT: dict[str, set[str]] = {
    "admissions": {"admissions"},
    "tuition": {"tuition"},
    "scholarship": {"scholarship"},
    "faculties": {"faculty", "study_program", "lecturer"},
    "study_programs": {"study_program", "faculty"},
    "lecturers_staff": {"lecturer", "faculty"},
    "academic_calendar": {"academic_calendar"},
    "academic_regulations": {"academic_regulations"},
    "student_services": {"student_services"},
    "campus_information": {"campus"},
    "sia": {"sia"},
    "sso": {"sso"},
}

# Labelled follow-up vs new-topic cases (Batch 6 follow-up accuracy).
FOLLOWUP_CASES: list[dict] = [
    {"history": ["Siapa dekan Fakultas Ilmu Komputer?"], "q": "Bagaimana cara saya login ke SIA?", "expected": False},
    {"history": ["Berapa biaya kuliah Informatika?"], "q": "Kalau untuk Akuntansi bagaimana?", "expected": True},
    {"history": ["Apa saja program studi di Fakultas Teknik?"], "q": "jelaskan lebih detail", "expected": True},
    {"history": ["Di mana lokasi kampus Meruya?"], "q": "Beasiswa apa saja yang tersedia?", "expected": False},
    {"history": ["Apa saja fasilitas kampus Meruya?"], "q": "yang lainnya?", "expected": True},
    {"history": ["Bagaimana cara daftar PMB?"], "q": "Berapa biayanya?", "expected": True},
    {"history": ["Siapa rektor UMB?"], "q": "Bagaimana cara reset password SSO?", "expected": False},
    {"history": [], "q": "Bagaimana cara akses SIA?", "expected": False},
    {"history": ["Apa itu SIA?"], "q": "Bagaimana cara mengaksesnya?", "expected": True},
    {"history": ["Beasiswa apa saja yang ada?"], "q": "Apa syarat KIP Kuliah?", "expected": True},
    {"history": ["Di mana perpustakaan UMB?"], "q": "Berapa biaya kuliah Teknik Sipil?", "expected": False},
    {"history": ["Program studi di FEB apa saja?"], "q": "yang S2 bagaimana?", "expected": True},
]


def evaluate_followup_accuracy(cases: list[dict] | None = None) -> dict:
    """Accuracy of detect_followup() against the labelled cases."""
    from app.rag.intent_router import detect_followup

    cases = cases or FOLLOWUP_CASES
    correct = 0
    errors: list[dict] = []
    for case in cases:
        history = [{"role": "user", "content": m} for m in case["history"]]
        pred = detect_followup(case["q"], history)
        if pred == case["expected"]:
            correct += 1
        else:
            errors.append({"q": case["q"], "expected": case["expected"], "predicted": pred})
    return {"n": len(cases), "accuracy": round(correct / len(cases), 3) if cases else None, "errors": errors}

# Quality gates that decide whether a phase is "done" (mission success criteria).
TARGETS = {"answerability": 0.90, "groundedness": 0.95, "faithfulness": 0.95, "hallucination": 0.02}

_CONFIDENCE_NUM = {"high": 0.9, "medium": 0.6, "low": 0.3}


def load_dataset(path: str | Path | None, entities_path: str | Path | None) -> list[dict]:
    """Load the committed benchmark, or regenerate it from entities on the fly."""
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if DEFAULT_DATASET.exists():
        return json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    return generate_benchmark(load_entities(entities_path))


def _has_labels(item: dict) -> bool:
    return any(
        item.get(key)
        for key in ("expected_hosts", "expected_urls", "expected_url_contains", "expected_chunk_ids", "expected_source_types")
    )


def _stratified_sample(questions: list[dict], per_category: int) -> set[str]:
    """Evenly-spaced, deterministic sample of ids per category (variety of qtypes)."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for item in questions:
        by_cat[item["category"]].append(item)
    chosen: set[str] = set()
    for items in by_cat.values():
        ordered = sorted(items, key=lambda row: row["id"])
        if per_category >= len(ordered):
            chosen.update(row["id"] for row in ordered)
            continue
        step = len(ordered) / per_category
        for index in range(per_category):
            chosen.add(ordered[int(index * step)]["id"])
    return chosen


_TYPED_GRAPH_CACHE: dict[str, object] = {}


def _structured_contexts(db, question: str, settings) -> list[dict]:
    """FAQ + entity + typed-graph contexts (the Phase 2-4 structured layers),
    sorted by score — identical to what ``run_umb_agent`` pins above vector."""
    structured: list[dict] = []
    try:
        from app.retrieval.faq_retriever import match_faq

        structured.extend(match_faq(db, question))
    except Exception:
        pass
    try:
        from app.retrieval.entity_retriever import query_entities

        structured.extend(query_entities(db, question, root_domain=settings.allowed_domain))
    except Exception:
        pass
    if getattr(settings, "typed_graph_enabled", True):
        try:
            from app.graph.typed_graph_store import load_typed_graph, typed_expansion_contexts

            path = getattr(settings, "typed_graph_path", None)
            graph = _TYPED_GRAPH_CACHE.get(path) if path else None
            if graph is None and path:
                graph = load_typed_graph(path)
                if graph is not None:
                    _TYPED_GRAPH_CACHE[path] = graph
            if graph is not None:
                structured.extend(
                    typed_expansion_contexts(
                        question, graph, root_domain=settings.allowed_domain,
                        limit=getattr(settings, "typed_graph_expansion_top_k", 3),
                    )
                )
        except Exception:
            pass
    structured.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
    return structured


def _merge_dedup(structured: list[dict], vector: list[dict], top_k: int) -> list[dict]:
    """Pin NON-demoted structured contexts above vector; intent-demoted structured
    contexts join the vector pool and compete by score. Dedupe by url, cap top_k."""
    pinned = [c for c in structured if not c.get("intent_demoted")]
    demoted = [c for c in structured if c.get("intent_demoted")]
    pool = demoted + vector
    pool.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
    merged: list[dict] = []
    seen: set[str] = set()
    for ctx in pinned + pool:
        key = (ctx.get("url") or "") + "|" + (ctx.get("chunk_text") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        merged.append(ctx)
    return merged[:top_k]


def _retrieve(retriever: HybridRetriever, db, question: str, intent: str, top_k: int, strategy: str, settings) -> list[dict]:
    if intent in {"out_of_scope", "unsafe_private_data"}:
        return []
    # ``dense`` is one indexed pgvector call (fast, ~1s); ``hybrid`` adds the
    # keyword ILIKE scans (the dominant latency on this corpus). ``agent`` runs the
    # full production structured pipeline (FAQ -> entity -> typed graph) pinned above
    # the dense vector path — the all-layers measurement at full-corpus scale.
    if strategy in {"agent", "agent_hybrid"}:
        structured = _structured_contexts(db, question, settings)
        # ``agent`` uses the fast dense vector path (full-corpus lower bound);
        # ``agent_hybrid`` uses the production keyword+dense vector path
        # (production-representative, slow) — run on a stratified sample.
        vector = retriever.search(question, top_k=top_k) if strategy == "agent_hybrid" else retriever.search_dense(question, top_k=top_k)
        merged = _merge_dedup(structured, vector, top_k * 2)
        # v3 P2: intent-aware host hard filter (same as the production agent).
        from app.rag.intent_router import apply_intent_host_filter

        apply_intent_host_filter(question, merged)
        # re-pin structured (non-demoted) above vector, then cap.
        pinned = [c for c in merged if c.get("source_type") in {"faq", "entity", "graph"} and not c.get("intent_demoted")]
        rest = [c for c in merged if c not in pinned]
        return (pinned + rest)[:top_k]
    if strategy == "dense":
        return retriever.search_dense(question, top_k=top_k)
    return retriever.search(question, top_k=top_k)


def run_benchmark(
    questions: list[dict],
    *,
    db,
    top_k: int = 5,
    strategy: str = "hybrid",
    retriever: HybridRetriever | None = None,
    embedder=None,
    generation_sample: set[str] | None = None,
    provider_override: str | None = None,
) -> dict:
    settings = get_settings()
    dense_enabled = True if strategy == "dense" else None
    retriever = retriever or HybridRetriever(db, root_domain=settings.allowed_domain, embedder=embedder, dense_enabled=dense_enabled)
    generation_sample = generation_sample or set()
    checker = LexicalEntailmentChecker() if generation_sample else None
    generate_answer = None
    if generation_sample:
        from app.rag.answer_generator import generate_answer as _gen

        generate_answer = _gen

    records: list[dict] = []
    for item in questions:
        is_control = item["category"] in CONTROL_CATEGORIES
        started = time.perf_counter()
        intent = classify_intent(item["question"]).intent
        contexts = _retrieve(retriever, db, item["question"], intent, top_k, strategy, settings)
        latency_ms = (time.perf_counter() - started) * 1000.0

        sources_found = bool(contexts)
        top_host = (contexts[0].get("hostname") or "").lower() if contexts else None
        official_top = bool(top_host) and host_authority(top_host, settings.allowed_domain) >= 0.5
        _layer_map = {"faq": "FAQ", "entity": "Entity", "graph": "GraphRAG"}
        top_source_layer = _layer_map.get(contexts[0].get("source_type"), "Vector") if contexts else None
        structured_in_topk = sum(1 for c in contexts if c.get("source_type") in {"faq", "entity", "graph"})
        # Batch 6: which layers contributed a context in top-k, and intent routing.
        _present = {c.get("source_type") for c in contexts}
        layers_present = {
            "FAQ": "faq" in _present,
            "Entity": "entity" in _present,
            "GraphRAG": "graph" in _present,
            "Vector": any(t not in {"faq", "entity", "graph"} for t in _present),
        }
        from app.rag.intent_router import detect_intent

        intent_pred = detect_intent(item["question"])
        expected_intents = _CATEGORY_EXPECTED_INTENT.get(item["category"])
        intent_correct = None if expected_intents is None else (intent_pred in expected_intents)
        target_rank = _target_rank(item, contexts)
        target_hit = None if target_rank is None else target_rank > 0
        noisy_at_1 = _is_noisy(item, contexts[0]) if contexts else False
        retrieved_urls = [c.get("url") for c in contexts if c.get("url")]

        if is_control:
            # A control is "answered" (bad) only if it surfaced official sources.
            answerable = sources_found
            correct_abstention = not sources_found
        else:
            # Answerable = retrieval surfaced an official, on-topic source the
            # generator could ground on (expected-source hit when labelled, else
            # any official top result).
            answerable = bool(sources_found and (target_hit if target_hit is not None else official_top) and not noisy_at_1)
            correct_abstention = None

        record = {
            "id": item["id"],
            "question": item["question"],
            "category": item["category"],
            "qtype": item.get("qtype"),
            "lang": item.get("lang"),
            "audience": item.get("audience"),
            "answerable": answerable,
            "grounded": None,
            "hallucinated": None,
            "retrieved_sources": retrieved_urls,
            "confidence": None,
            "latency_ms": round(latency_ms, 1),
            # diagnostics
            "is_control": is_control,
            "sources_found": sources_found,
            "official_top": official_top,
            "target_hit": target_hit,
            "target_rank": target_rank,
            "noisy_at_1": noisy_at_1,
            "correct_abstention": correct_abstention,
            "retrieved_hosts": sorted({(c.get("hostname") or "") for c in contexts if c.get("hostname")}),
            "top_source_layer": top_source_layer,
            "structured_in_topk": structured_in_topk,
            "layers_present": layers_present,
            "intent_pred": intent_pred,
            "intent_correct": intent_correct,
            "generated": False,
        }

        if generate_answer is not None and item["id"] in generation_sample:
            gen_started = time.perf_counter()
            result = generate_answer(
                question=item["question"],
                contexts=contexts,
                recent_messages=[],
                memories=[],
                provider_override=provider_override,
                language=item.get("lang", "id"),
            )
            record["gen_latency_ms"] = round((time.perf_counter() - gen_started) * 1000.0, 1)
            record["generated"] = True
            not_found = bool(result.get("not_found"))
            answer_text = result.get("answer") or ""
            # Align citation ids to the answer's OWN sources (the [n] markers map to
            # result["sources"] order, not to raw retrieval order); back them with the
            # retrieved chunk text by URL. Falls back to retrieval order when the answer
            # carries no sources. Avoids false hallucination flags from misaligned maps.
            url_to_text: dict[str, str] = {}
            for ctx in contexts:
                url = ctx.get("url")
                if url and url not in url_to_text:
                    url_to_text[url] = ctx.get("chunk_text") or ""
            answer_sources = result.get("sources") or []
            if answer_sources:
                contexts_by_citation = {i + 1: {"chunk_text": url_to_text.get(src.get("url"), src.get("snippet") or "")} for i, src in enumerate(answer_sources)}
            else:
                contexts_by_citation = {i + 1: {"chunk_text": c.get("chunk_text") or ""} for i, c in enumerate(contexts)}
            faithfulness = faithfulness_score(answer_text, contexts_by_citation, checker) if not not_found else 1.0
            answered = not not_found
            record["confidence"] = _CONFIDENCE_NUM.get(str(result.get("confidence") or "").lower())
            record["faithfulness"] = round(faithfulness, 3)
            record["answer_preview"] = answer_text[:160]
            if is_control:
                # Controls must abstain; any substantive answer is a hallucination.
                record["grounded"] = None
                record["hallucinated"] = answered
            else:
                record["grounded"] = bool(answered and faithfulness >= 0.5 and sources_found)
                record["hallucinated"] = bool(answered and faithfulness < 0.5)

        records.append(record)

    return _aggregate(records, questions, top_k=top_k, strategy=strategy, generated=bool(generation_sample))


def _rate(values: list[bool]) -> float | None:
    return round(sum(1 for v in values if v) / len(values), 3) if values else None


def _aggregate(records: list[dict], questions: list[dict], *, top_k: int, strategy: str = "hybrid", generated: bool = False) -> dict:
    answer_bearing = [r for r in records if not r["is_control"]]
    controls = [r for r in records if r["is_control"]]
    labelled = [r for r in answer_bearing if r["target_hit"] is not None]
    gen_records = [r for r in answer_bearing if r["generated"]]

    by_category: dict[str, dict] = {}
    cat_rows: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        cat_rows[record["category"]].append(record)
    for category, rows in sorted(cat_rows.items()):
        ab = [r for r in rows if not r["is_control"]]
        lab = [r for r in ab if r["target_hit"] is not None]
        gen = [r for r in rows if r["generated"]]
        gen_ans = [r for r in gen if not r["is_control"]]
        by_category[category] = {
            "n": len(rows),
            "is_control": rows[0]["is_control"],
            "answerability": _rate([r["answerable"] for r in ab]) if ab else None,
            "sources_found_rate": _rate([r["sources_found"] for r in rows]),
            "retrieval_accuracy": _rate([bool(r["target_hit"]) for r in lab]) if lab else None,
            "citation_failure_rate": _rate([r["noisy_at_1"] for r in rows]),
            "median_latency_ms": round(statistics.median([r["latency_ms"] for r in rows]), 1) if rows else None,
            "generated_n": len(gen),
            "groundedness": _rate([bool(r["grounded"]) for r in gen_ans]) if gen_ans else None,
            "hallucination_rate": _rate([bool(r["hallucinated"]) for r in gen]) if gen else None,
        }

    latencies = [r["latency_ms"] for r in records]
    weak = [
        {
            "category": cat,
            "answerability": meta["answerability"],
            "sample_failures": [r["question"] for r in cat_rows[cat] if not r["is_control"] and not r["answerable"]][:5],
        }
        for cat, meta in by_category.items()
        if not meta["is_control"] and (meta["answerability"] or 0.0) < TARGETS["answerability"]
    ]
    retrieval_failures = [
        {"id": r["id"], "question": r["question"], "category": r["category"], "retrieved_hosts": r["retrieved_hosts"]}
        for r in answer_bearing
        if not r["answerable"]
    ]
    citation_failures = [
        {"id": r["id"], "question": r["question"], "category": r["category"], "top_host": (r["retrieved_hosts"][0] if r["retrieved_hosts"] else None)}
        for r in records
        if r["noisy_at_1"]
    ]

    layer_dist: dict[str, int] = defaultdict(int)
    for r in answer_bearing:
        if r.get("top_source_layer"):
            layer_dist[r["top_source_layer"]] += 1

    # Batch 6: layer hit rates (contributed a context in top-k) + intent routing.
    layer_hit_rates = {
        layer: _rate([bool((r.get("layers_present") or {}).get(layer)) for r in answer_bearing])
        for layer in ("FAQ", "Entity", "GraphRAG", "Vector")
    }
    intent_labelled = [r for r in answer_bearing if r.get("intent_correct") is not None]
    intent_by_cat: dict[str, list[bool]] = defaultdict(list)
    for r in intent_labelled:
        intent_by_cat[r["category"]].append(bool(r["intent_correct"]))
    intent_routing = {
        "accuracy": _rate([bool(r["intent_correct"]) for r in intent_labelled]),
        "by_category": {c: _rate(v) for c, v in sorted(intent_by_cat.items())},
        "misroutes": [
            {"question": r["question"], "category": r["category"], "predicted_intent": r["intent_pred"]}
            for r in intent_labelled if not r["intent_correct"]
        ][:30],
    }
    # Tavily-fallback proxy: answer-bearing questions whose retrieval confidence was
    # insufficient (would escalate to the live web fallback).
    from app.rag.discovery_cache import evaluate_confidence

    insufficient = 0
    for r in records:
        if r["is_control"]:
            continue
        # reconstruct minimal contexts for the confidence check from diagnostics
        # (top layer + hosts) — cheap proxy: sufficient if a structured layer was top
        # or an official host was at rank 1.
        if r.get("top_source_layer") in {"FAQ", "Entity", "GraphRAG"} or r.get("official_top"):
            continue
        insufficient += 1
    tavily_fallback_rate = round(insufficient / len(answer_bearing), 3) if answer_bearing else None

    sorted_lat = sorted(latencies)

    def _pct(p: float) -> float | None:
        return round(sorted_lat[max(0, int(p * len(sorted_lat)) - 1)], 1) if sorted_lat else None

    overall = {
        "answerability": _rate([r["answerable"] for r in answer_bearing]),
        "retrieval_accuracy": _rate([bool(r["target_hit"]) for r in labelled]),
        "coverage": _rate([r["sources_found"] for r in answer_bearing]),
        "citation_failure_rate": _rate([r["noisy_at_1"] for r in answer_bearing]),
        "control_abstention_correct": _rate([r["correct_abstention"] for r in controls]) if controls else None,
        "answer_source_layers": dict(sorted(layer_dist.items(), key=lambda kv: -kv[1])),
        "structured_layer_share": _rate([r.get("top_source_layer") in {"FAQ", "Entity", "GraphRAG"} for r in answer_bearing]),
        "layer_hit_rates": layer_hit_rates,
        "intent_routing_accuracy": intent_routing["accuracy"],
        "tavily_fallback_rate": tavily_fallback_rate,
        "latency_ms": {
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": _pct(0.95),
            "p99": _pct(0.99),
        },
    }
    if generated:
        gen_ans = [r for r in gen_records]
        overall["generation"] = {
            "evaluated": len(gen_records),
            "groundedness": _rate([bool(r["grounded"]) for r in gen_ans]),
            "hallucination_rate": _rate([bool(r["hallucinated"]) for r in records if r["generated"]]),
            "faithfulness_mean": round(statistics.mean([r.get("faithfulness", 0.0) for r in gen_records]), 3) if gen_records else None,
            "control_hallucination_rate": _rate([bool(r["hallucinated"]) for r in controls if r["generated"]]) if any(r["generated"] for r in controls) else None,
        }

    targets_met = {
        "answerability": (overall["answerability"] or 0) >= TARGETS["answerability"],
    }
    if generated and overall.get("generation"):
        gen = overall["generation"]
        targets_met["groundedness"] = (gen["groundedness"] or 0) >= TARGETS["groundedness"]
        targets_met["hallucination"] = (gen["hallucination_rate"] or 1) <= TARGETS["hallucination"]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset_size": len(records),
        "answer_bearing_questions": len(answer_bearing),
        "control_questions": len(controls),
        "top_k": top_k,
        "retrieval_strategy": strategy,
        "targets": TARGETS,
        "targets_met": targets_met,
        "overall": overall,
        "intent_routing": intent_routing,
        "by_category": by_category,
        "missing_knowledge_areas": sorted(weak, key=lambda row: row["answerability"] or 0.0),
        "retrieval_failure_count": len(retrieval_failures),
        "citation_failure_count": len(citation_failures),
        "retrieval_failures": retrieval_failures[:60],
        "citation_failures": citation_failures[:60],
        "results": records,
    }


def _print_summary(report: dict) -> None:
    o = report["overall"]
    print(f"\n=== UMB Answerability Benchmark ({report['dataset_size']} Qs, top_k={report['top_k']}) ===")
    print(f"Answerability (answer-bearing): {o['answerability']}  [target >= {TARGETS['answerability']}]")
    print(f"Retrieval accuracy (labelled) : {o['retrieval_accuracy']}")
    print(f"Coverage (any official source): {o['coverage']}")
    print(f"Citation-failure rate         : {o['citation_failure_rate']}")
    print(f"Control abstention correct    : {o['control_abstention_correct']}")
    if o.get("answer_source_layers"):
        print(f"Answer source layers          : {o['answer_source_layers']}  (structured share {o.get('structured_layer_share')})")
    if o.get("layer_hit_rates"):
        print(f"Layer hit rates (in top-k)    : {o['layer_hit_rates']}")
    if o.get("intent_routing_accuracy") is not None:
        print(f"Intent routing accuracy       : {o['intent_routing_accuracy']}")
    if o.get("tavily_fallback_rate") is not None:
        print(f"Tavily fallback rate (proxy)  : {o['tavily_fallback_rate']}")
    if report.get("follow_up_accuracy"):
        print(f"Follow-up routing accuracy    : {report['follow_up_accuracy']['accuracy']}  (n={report['follow_up_accuracy']['n']})")
    print(f"Latency ms (median/p95/p99)   : {o['latency_ms']['median']} / {o['latency_ms']['p95']} / {o['latency_ms'].get('p99')}")
    if o.get("generation"):
        g = o["generation"]
        print(f"Generation sample             : {g['evaluated']} Qs")
        print(f"  Groundedness                : {g['groundedness']}  [target >= {TARGETS['groundedness']}]")
        print(f"  Hallucination rate          : {g['hallucination_rate']}  [target <= {TARGETS['hallucination']}]")
        print(f"  Faithfulness (mean)         : {g['faithfulness_mean']}")
    print("\n-- By category (answerability | retrieval_acc | citation_fail | n) --")
    for cat, meta in sorted(report["by_category"].items(), key=lambda kv: (kv[1]["is_control"], kv[1]["answerability"] or 0.0)):
        tag = " (control)" if meta["is_control"] else ""
        print(f"  {cat:22s} ans={str(meta['answerability']):6} acc={str(meta['retrieval_accuracy']):6} cite_fail={str(meta['citation_failure_rate']):6} n={meta['n']}{tag}")
    if report["missing_knowledge_areas"]:
        print("\n-- Weak domains (answerability below target) --")
        for area in report["missing_knowledge_areas"]:
            print(f"  {area['category']}: {area['answerability']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the UMB answerability benchmark")
    parser.add_argument("--dataset", default=None, help="Path to benchmark JSON (default: committed umb_benchmark.json)")
    parser.add_argument("--entities", default=None, help="Mined entities JSON (used only if no dataset exists)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--strategy",
        choices=("dense", "hybrid", "agent", "agent_hybrid"),
        default="dense",
        help="dense = one indexed pgvector call (fast full-corpus run); hybrid = production keyword+dense (slow); agent = structured layers + dense vector (fast full-corpus); agent_hybrid = structured layers + production keyword+dense vector (slow, production-representative sample).",
    )
    parser.add_argument("--out", default="data/reports/benchmark_report.json")
    parser.add_argument("--with-generation", action="store_true", help="Also run the LLM generation tier on a stratified sample")
    parser.add_argument("--sample-per-category", type=int, default=2, help="Generation-tier questions per category")
    parser.add_argument("--provider", default=None, help="provider_override for the generation tier")
    parser.add_argument("--limit", type=int, default=None, help="Cap number of questions (smoke runs)")
    parser.add_argument("--stratify", type=int, default=None, help="Run only N questions per category (production-representative sample for slow hybrid runs)")
    args = parser.parse_args()

    questions = load_dataset(args.dataset, args.entities)
    if args.stratify:
        keep = _stratified_sample(questions, args.stratify)
        questions = [q for q in questions if q["id"] in keep]
    if args.limit:
        questions = questions[: args.limit]
    sample = _stratified_sample(questions, args.sample_per_category) if args.with_generation else set()

    embedder = get_embedder()
    with get_session_local()() as db:
        report = run_benchmark(
            questions,
            db=db,
            top_k=args.top_k,
            strategy=args.strategy,
            embedder=embedder,
            generation_sample=sample,
            provider_override=args.provider,
        )
    # Batch 6: follow-up routing accuracy (independent of the retrieval run).
    report["follow_up_accuracy"] = evaluate_followup_accuracy()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_summary(report)
    print(f"\nFull report -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
