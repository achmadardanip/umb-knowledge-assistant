from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.llm.provider_factory import normalize_provider
from app.retrieval.hybrid_retriever import HybridRetriever


QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")


def evaluate(question_path: str | Path = QUESTIONS_PATH, top_k: int = 5) -> dict:
    questions = json.loads(Path(question_path).read_text(encoding="utf-8"))
    settings = get_settings()
    provider = normalize_provider(None)
    rows = []
    source_type_distribution: Counter[str] = Counter()
    with get_session_local()() as db:
        retriever = HybridRetriever(db, root_domain=settings.allowed_domain)
        for item in questions:
            contexts = retriever.search(item["question"], top_k=top_k)
            citations = len({context.get("url") for context in contexts if context.get("url")})
            for context in contexts:
                source_type_distribution[context.get("source_type") or "unknown"] += 1
            rows.append(
                {
                    "id": item["id"],
                    "category": item["category"],
                    "question": item["question"],
                    "sources_found": bool(contexts),
                    "citation_count": citations,
                    "not_found": not bool(contexts),
                    "provider_used": provider,
                    "memory_used": False,
                    "source_types": [context.get("source_type") for context in contexts],
                }
            )
    report = {
        "total_questions": len(rows),
        "not_found_rate": sum(1 for row in rows if row["not_found"]) / max(len(rows), 1),
        "provider_used": provider,
        "memory_used": False,
        "source_type_distribution": dict(source_type_distribution),
        "results": rows,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate UMB RAG retrieval")
    parser.add_argument("--questions", default=str(QUESTIONS_PATH))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="data/evaluation_report.json")
    args = parser.parse_args()
    report = evaluate(args.questions, top_k=args.top_k)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

