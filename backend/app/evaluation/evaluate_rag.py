"""RAG evaluation harness.

Retrieval-only by default (CI-safe, no LLM/network): reports retrieval hit-rate,
abstention correctness against gold labels, and stratified distributions by
category / volatility / stakes. Offline lexical grounding fixtures exercise
faithfulness and citation metrics without an LLM judge or network call.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.evaluation.metrics import abstention_outcome, citation_metrics, faithfulness_score
from app.ingestion.embedder import get_embedder
from app.retrieval.hybrid_retriever import HybridRetriever
from app.verification.entailment import LexicalEntailmentChecker

QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")
GROUNDING_CASES_PATH = Path(__file__).with_name("grounding_cases.json")


def load_questions(path: str | Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _target_hit(item: dict, contexts: list[dict]) -> bool | None:
    expected_hosts = {value.lower() for value in item.get("expected_hosts", [])}
    expected_urls = set(item.get("expected_urls", []))
    expected_chunk_ids = {str(value) for value in item.get("expected_chunk_ids", [])}
    expected_source_types = set(item.get("expected_source_types", []))
    if not any((expected_hosts, expected_urls, expected_chunk_ids, expected_source_types)):
        return None
    return any(
        (context.get("hostname") or "").lower() in expected_hosts
        or context.get("url") in expected_urls
        or str(context.get("chunk_id")) in expected_chunk_ids
        or context.get("source_type") in expected_source_types
        for context in contexts
    )


def evaluate(
    questions: list[dict],
    *,
    db,
    top_k: int = 5,
    strategy: str = "current",
    retriever: HybridRetriever | None = None,
    embedder=None,
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

    for item in questions:
        if strategy == "dense":
            contexts = retriever.search_dense(item["question"], top_k=top_k)
        else:
            contexts = retriever.search(item["question"], top_k=top_k)
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
        target_hit = _target_hit(item, contexts)
        if target_hit is not None:
            target_total += 1
            target_hits += int(target_hit)

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
                "retrieved_hosts": sorted({context.get("hostname") for context in contexts if context.get("hostname")}),
            }
        )

    return {
        "retrieval_strategy": strategy,
        "total_questions": len(rows),
        "retrieval_hit_rate": in_scope_hits / in_scope_total if in_scope_total else 0.0,
        "labelled_target_hit_rate": target_hits / target_total if target_total else None,
        "labelled_target_questions": target_total,
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
) -> dict[str, dict]:
    return {
        strategy: evaluate(
            questions,
            db=db,
            top_k=top_k,
            strategy=strategy,
            embedder=embedder if strategy in {"dense", "hybrid"} else None,
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
    args = parser.parse_args()
    questions = load_questions(args.questions)
    strategies = [value.strip() for value in args.strategies.split(",") if value.strip()]
    unknown = sorted(set(strategies) - {"current", "keyword", "dense", "hybrid"})
    if unknown:
        parser.error(f"Unknown strategies: {', '.join(unknown)}")
    shared_embedder = get_embedder() if any(value in {"dense", "hybrid"} for value in strategies) else None
    with get_session_local()() as db:
        reports = evaluate_strategies(
            questions,
            db=db,
            strategies=strategies,
            top_k=args.top_k,
            embedder=shared_embedder,
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
