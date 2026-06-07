"""RAG evaluation harness.

Retrieval-only by default (CI-safe, no LLM/network): reports retrieval hit-rate,
abstention correctness against gold labels, and stratified distributions by
category / volatility / stakes. The generation-quality metrics (faithfulness,
citation precision/recall) live in ``app.evaluation.metrics`` and are wired in
once a provider is available; they double as the C²GV calibration signal.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.evaluation.metrics import abstention_outcome
from app.retrieval.hybrid_retriever import HybridRetriever

QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")


def load_questions(path: str | Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate(questions: list[dict], *, db, top_k: int = 5) -> dict:
    settings = get_settings()
    retriever = HybridRetriever(db, root_domain=settings.allowed_domain)
    rows: list[dict] = []
    abstention: Counter[str] = Counter()
    category_distribution: Counter[str] = Counter()
    volatility_distribution: Counter[str] = Counter()
    stakes_distribution: Counter[str] = Counter()
    in_scope_total = 0
    in_scope_hits = 0

    for item in questions:
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
                "retrieved_hosts": sorted({context.get("hostname") for context in contexts if context.get("hostname")}),
            }
        )

    return {
        "total_questions": len(rows),
        "retrieval_hit_rate": in_scope_hits / in_scope_total if in_scope_total else 0.0,
        "not_found_rate": sum(1 for row in rows if row["not_found"]) / max(len(rows), 1),
        "abstention": dict(abstention),
        "category_distribution": dict(category_distribution),
        "volatility_distribution": dict(volatility_distribution),
        "stakes_distribution": dict(stakes_distribution),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate UMB RAG retrieval and grounding")
    parser.add_argument("--questions", default=str(QUESTIONS_PATH))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="data/evaluation_report.json")
    args = parser.parse_args()
    questions = load_questions(args.questions)
    with get_session_local()() as db:
        report = evaluate(questions, db=db, top_k=args.top_k)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
