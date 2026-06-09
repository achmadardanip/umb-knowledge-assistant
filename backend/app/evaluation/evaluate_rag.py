"""RAG evaluation harness.

Retrieval-only by default (CI-safe, no LLM/network): reports retrieval hit-rate,
abstention correctness against gold labels, and stratified distributions by
category / volatility / stakes. Offline lexical grounding fixtures exercise
faithfulness and citation metrics without an LLM judge or network call.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.evaluation.metrics import abstention_outcome, citation_metrics, faithfulness_score
from app.ingestion.embedder import get_embedder
from app.retrieval.hybrid_retriever import HybridRetriever
from app.verification.entailment import LexicalEntailmentChecker

QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")
RANKING_QUESTIONS_PATH = Path(__file__).with_name("ranking_questions.json")
GROUNDING_CASES_PATH = Path(__file__).with_name("grounding_cases.json")


def load_questions(path: str | Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _target_match(item: dict, context: dict) -> bool:
    expected_hosts = {value.lower() for value in item.get("expected_hosts", [])}
    expected_urls = set(item.get("expected_urls", []))
    expected_url_contains = [value.lower() for value in item.get("expected_url_contains", [])]
    expected_chunk_ids = {str(value) for value in item.get("expected_chunk_ids", [])}
    expected_source_types = set(item.get("expected_source_types", []))
    url = context.get("url") or ""
    return (
        (context.get("hostname") or "").lower() in expected_hosts
        or url in expected_urls
        or any(value in url.lower() for value in expected_url_contains)
        or str(context.get("chunk_id")) in expected_chunk_ids
        or context.get("source_type") in expected_source_types
    )


def _target_rank(item: dict, contexts: list[dict]) -> int | None:
    if not any(
        (
            item.get("expected_hosts"),
            item.get("expected_urls"),
            item.get("expected_url_contains"),
            item.get("expected_chunk_ids"),
            item.get("expected_source_types"),
        )
    ):
        return None
    return next(
        (rank for rank, context in enumerate(contexts, start=1) if _target_match(item, context)),
        0,
    )


def _is_noisy(item: dict, context: dict | None) -> bool:
    if context is None:
        return False
    host = (context.get("hostname") or "").lower()
    url = (context.get("url") or "").lower()
    return (
        host in {value.lower() for value in item.get("forbidden_hosts", [])}
        or any(value.lower() in url for value in item.get("forbidden_url_contains", []))
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate(
    questions: list[dict],
    *,
    db,
    top_k: int = 5,
    strategy: str = "current",
    retriever: HybridRetriever | None = None,
    embedder=None,
    reranker_enabled: bool | None = None,
) -> dict:
    settings = get_settings()
    if strategy not in {"current", "keyword", "dense", "hybrid"}:
        raise ValueError(f"Unknown retrieval strategy: {strategy}")
    if retriever is None:
        dense_enabled = None if strategy == "current" else strategy == "hybrid"
        retriever = HybridRetriever(
            db,
            root_domain=settings.allowed_domain,
            embedder=embedder,
            dense_enabled=dense_enabled,
        )
    rows: list[dict] = []
    abstention: Counter[str] = Counter()
    category_distribution: Counter[str] = Counter()
    volatility_distribution: Counter[str] = Counter()
    stakes_distribution: Counter[str] = Counter()
    in_scope_total = 0
    in_scope_hits = 0
    target_total = 0
    target_hits = 0
    hit_at_1 = 0
    hit_at_3 = 0
    reciprocal_rank_total = 0.0
    noisy_at_1 = 0
    latency_ms: list[float] = []

    for item in questions:
        started = time.perf_counter()
        if strategy == "dense":
            if reranker_enabled is None:
                contexts = retriever.search_dense(item["question"], top_k=top_k)
            else:
                contexts = retriever.search_dense(
                    item["question"],
                    top_k=top_k,
                    apply_model_reranker=reranker_enabled,
                )
        else:
            if reranker_enabled is None:
                contexts = retriever.search(item["question"], top_k=top_k)
            else:
                contexts = retriever.search(
                    item["question"],
                    top_k=top_k,
                    apply_model_reranker=reranker_enabled,
                )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latency_ms.append(elapsed_ms)
        predicted_not_found = not bool(contexts)
        expected_not_found = bool(item.get("expected_not_found"))
        category_distribution[item.get("category", "unknown")] += 1
        volatility_distribution[item.get("volatility", "unknown")] += 1
        stakes_distribution[item.get("stakes", "unknown")] += 1

        outcome = None
        if "expected_not_found" in item:
            outcome = abstention_outcome(
                predicted_not_found=predicted_not_found, expected_not_found=expected_not_found
            )
            abstention[outcome] += 1

        if not expected_not_found:
            in_scope_total += 1
            if contexts:
                in_scope_hits += 1
        target_rank = _target_rank(item, contexts)
        target_hit = None if target_rank is None else target_rank > 0
        if target_rank is not None:
            target_total += 1
            target_hits += int(target_hit)
            hit_at_1 += int(target_rank == 1)
            hit_at_3 += int(0 < target_rank <= 3)
            reciprocal_rank_total += 1.0 / target_rank if target_rank else 0.0
            noisy_at_1 += int(_is_noisy(item, contexts[0] if contexts else None))

        rows.append(
            {
                "id": item.get("id"),
                "category": item.get("category"),
                "lang": item.get("lang"),
                "volatility": item.get("volatility"),
                "stakes": item.get("stakes"),
                "question": item["question"],
                "sources_found": bool(contexts),
                "citation_count": len({context.get("url") for context in contexts if context.get("url")}),
                "not_found": predicted_not_found,
                "expected_not_found": expected_not_found if "expected_not_found" in item else None,
                "abstention_outcome": outcome,
                "target_hit": target_hit,
                "target_rank": target_rank,
                "reciprocal_rank": 1.0 / target_rank if target_rank else 0.0,
                "noisy_at_1": _is_noisy(item, contexts[0] if contexts else None),
                "latency_ms": elapsed_ms,
                "retrieved_hosts": sorted({context.get("hostname") for context in contexts if context.get("hostname")}),
                "retrieved_urls": [context.get("url") for context in contexts if context.get("url")],
            }
        )

    return {
        "retrieval_strategy": strategy,
        "reranker_enabled": reranker_enabled,
        "total_questions": len(rows),
        "retrieval_hit_rate": in_scope_hits / in_scope_total if in_scope_total else 0.0,
        "labelled_target_hit_rate": target_hits / target_total if target_total else None,
        "labelled_target_questions": target_total,
        "hit_at_1": hit_at_1 / target_total if target_total else None,
        "hit_at_3": hit_at_3 / target_total if target_total else None,
        "mrr": reciprocal_rank_total / target_total if target_total else None,
        "noisy_at_1_rate": noisy_at_1 / target_total if target_total else None,
        "latency_ms": {
            "median": statistics.median(latency_ms) if latency_ms else 0.0,
            "p95": _percentile(latency_ms, 0.95),
        },
        "not_found_rate": sum(1 for row in rows if row["not_found"]) / max(len(rows), 1),
        "abstention": dict(abstention),
        "category_distribution": dict(category_distribution),
        "volatility_distribution": dict(volatility_distribution),
        "stakes_distribution": dict(stakes_distribution),
        "results": rows,
    }


def evaluate_strategies(
    questions: list[dict],
    *,
    db,
    strategies: list[str],
    top_k: int = 5,
    embedder=None,
    reranker_enabled: bool | None = None,
) -> dict[str, dict]:
    return {
        strategy: evaluate(
            questions,
            db=db,
            top_k=top_k,
            strategy=strategy,
            embedder=embedder if strategy in {"dense", "hybrid"} else None,
            reranker_enabled=reranker_enabled,
        )
        for strategy in strategies
    }


def evaluate_grounding_cases(path: str | Path = GROUNDING_CASES_PATH) -> dict:
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    checker = LexicalEntailmentChecker()
    rows = []
    correct = 0
    for case in cases:
        contexts = {int(key): value for key, value in case.get("contexts_by_citation", {}).items()}
        faithfulness = faithfulness_score(case.get("answer", ""), contexts, checker)
        citations = citation_metrics(case.get("answer", ""), contexts, checker)
        predicted_faithful = faithfulness >= 0.5
        expected_faithful = bool(case.get("expected_faithful"))
        correct += int(predicted_faithful == expected_faithful)
        rows.append(
            {
                "id": case.get("id"),
                "faithfulness": faithfulness,
                "citation_precision": citations.precision,
                "citation_recall": citations.recall,
                "expected_faithful": expected_faithful,
                "correct": predicted_faithful == expected_faithful,
            }
        )
    return {
        "total_cases": len(rows),
        "classification_accuracy": correct / len(rows) if rows else 0.0,
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate UMB RAG retrieval and grounding")
    parser.add_argument("--questions", default=str(QUESTIONS_PATH))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="data/evaluation_report.json")
    parser.add_argument(
        "--strategies",
        default="current",
        help="Comma-separated retrieval strategies: current,keyword,dense,hybrid",
    )
    parser.add_argument("--grounding-cases", default=str(GROUNDING_CASES_PATH))
    parser.add_argument("--skip-grounding", action="store_true")
    parser.add_argument(
        "--reranker",
        choices=("current", "off", "on"),
        default="current",
        help="Use configured reranker state, force it off, or force it on.",
    )
    args = parser.parse_args()
    questions = load_questions(args.questions)
    strategies = [value.strip() for value in args.strategies.split(",") if value.strip()]
    unknown = sorted(set(strategies) - {"current", "keyword", "dense", "hybrid"})
    if unknown:
        parser.error(f"Unknown strategies: {', '.join(unknown)}")
    shared_embedder = get_embedder() if any(value in {"dense", "hybrid"} for value in strategies) else None
    reranker_enabled = None if args.reranker == "current" else args.reranker == "on"
    with get_session_local()() as db:
        reports = evaluate_strategies(
            questions,
            db=db,
            strategies=strategies,
            top_k=args.top_k,
            embedder=shared_embedder,
            reranker_enabled=reranker_enabled,
        )
    grounding = None if args.skip_grounding else evaluate_grounding_cases(args.grounding_cases)
    report = next(iter(reports.values())) if len(reports) == 1 else {"retrieval_strategies": reports}
    report["grounding"] = grounding
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
