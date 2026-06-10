"""Compare the local reranker against the current retrieval baseline."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.evaluation.evaluate_rag import (
    QUESTIONS_PATH,
    RANKING_QUESTIONS_PATH,
    evaluate,
    load_questions,
)
from app.ingestion.embedder import get_embedder
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.reranker import get_reranker


def _delta(after: float | None, before: float | None) -> float:
    return float(after or 0.0) - float(before or 0.0)


def _added_latency(after: dict, before: dict) -> dict[str, float]:
    before_by_id = {
        row["id"]: float(row["latency_ms"])
        for row in before["results"]
    }
    deltas = [
        float(row["latency_ms"]) - before_by_id[row["id"]]
        for row in after["results"]
        if row["id"] in before_by_id
    ]
    if not deltas:
        return {"median": 0.0, "p95": 0.0}
    ordered = sorted(deltas)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "median": statistics.median(deltas),
        "p95": ordered[p95_index],
    }


def benchmark(
    *,
    db,
    ranking_questions: list[dict],
    regression_questions: list[dict],
    top_k: int = 5,
) -> dict:
    settings = get_settings()
    embedder = get_embedder()
    retriever = HybridRetriever(
        db,
        root_domain=settings.allowed_domain,
        embedder=embedder,
        dense_enabled=True,
    )
    # Warm both local models before collecting latency.
    embedder.embed_query("warmup")
    get_reranker().score("warmup", ["warmup"])

    ranking_baseline = evaluate(
        ranking_questions,
        db=db,
        top_k=top_k,
        strategy="hybrid",
        retriever=retriever,
        reranker_enabled=False,
    )
    ranking_reranked = evaluate(
        ranking_questions,
        db=db,
        top_k=top_k,
        strategy="hybrid",
        retriever=retriever,
        reranker_enabled=True,
    )
    regression_baseline = evaluate(
        regression_questions,
        db=db,
        top_k=top_k,
        strategy="hybrid",
        retriever=retriever,
        reranker_enabled=False,
    )
    regression_reranked = evaluate(
        regression_questions,
        db=db,
        top_k=top_k,
        strategy="hybrid",
        retriever=retriever,
        reranker_enabled=True,
    )

    added_latency = _added_latency(ranking_reranked, ranking_baseline)
    checks = {
        "hit_at_1_improves_10pp": _delta(
            ranking_reranked["hit_at_1"], ranking_baseline["hit_at_1"]
        )
        >= 0.10,
        "mrr_improves_10pp": _delta(
            ranking_reranked["mrr"], ranking_baseline["mrr"]
        )
        >= 0.10,
        "hit_at_3_no_regression": float(ranking_reranked["hit_at_3"] or 0.0)
        >= float(ranking_baseline["hit_at_3"] or 0.0),
        "legacy_target_hit_no_regression": float(
            regression_reranked["labelled_target_hit_rate"] or 0.0
        )
        >= float(regression_baseline["labelled_target_hit_rate"] or 0.0),
        "legacy_retrieval_hit_no_regression": regression_reranked[
            "retrieval_hit_rate"
        ]
        >= regression_baseline["retrieval_hit_rate"],
        "added_median_latency_at_most_2500ms": added_latency["median"] <= 2500.0,
        "added_p95_latency_at_most_5000ms": added_latency["p95"] <= 5000.0,
    }
    return {
        "passed": all(checks.values()),
        "profile": {
            "model": settings.reranker_model,
            "candidate_k": settings.reranker_candidate_k,
            "batch_size": settings.reranker_batch_size,
            "max_length": settings.reranker_max_length,
            "device": settings.reranker_device,
        },
        "checks": checks,
        "quality_delta": {
            "hit_at_1": _delta(
                ranking_reranked["hit_at_1"], ranking_baseline["hit_at_1"]
            ),
            "hit_at_3": _delta(
                ranking_reranked["hit_at_3"], ranking_baseline["hit_at_3"]
            ),
            "mrr": _delta(ranking_reranked["mrr"], ranking_baseline["mrr"]),
        },
        "added_latency_ms": added_latency,
        "ranking_baseline": ranking_baseline,
        "ranking_reranked": ranking_reranked,
        "regression_baseline": regression_baseline,
        "regression_reranked": regression_reranked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark and gate the local BGE reranker")
    parser.add_argument("--ranking-questions", default=str(RANKING_QUESTIONS_PATH))
    parser.add_argument("--regression-questions", default=str(QUESTIONS_PATH))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out")
    args = parser.parse_args()

    with get_session_local()() as db:
        report = benchmark(
            db=db,
            ranking_questions=load_questions(args.ranking_questions),
            regression_questions=load_questions(args.regression_questions),
            top_k=args.top_k,
        )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        output = Path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        summary = {
            key: report[key]
            for key in ("passed", "profile", "checks", "quality_delta", "added_latency_ms")
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
