"""
P4 mini-validation runner — exercises the groundedness pipeline on a golden-dataset
subset and reports the five Phase-6 metrics:

    groundedness, citation_alignment, unsupported_claim_rate, regenerate_rate, abstain_rate

Generation is INJECTED (``generate(question) -> answer_payload``) so the aggregator is
decoupled from the (CPU/GPU-heavy) live LLM path: unit-testable here, and on a capable
host ``main()`` wires the real retrieval+generation with ``CGCV_ENTAILMENT_MODE=nli`` /
``GROUNDEDNESS_DECISION_ENABLED=true``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.evaluation.metrics import citation_alignment
from app.verification.groundedness import (
    DECISION_ABSTAIN,
    DECISION_REGENERATE,
    GroundednessVerifier,
)

_OUT = Path(__file__).resolve().parents[3] / "reports" / "golden_validation_report.json"


@dataclass
class ValidationRow:
    id: str
    question: str
    groundedness: float
    citation_alignment: float
    unsupported_claim_rate: float
    decision: str
    not_found: bool


def _contexts_by_citation(payload: dict) -> dict[int, dict]:
    """Map citation_id -> context using the answer payload's own source cards (each
    carries citation_id + url + chunk_text in the live path)."""
    mapping: dict[int, dict] = {}
    for src in payload.get("sources") or []:
        cid = src.get("citation_id")
        if cid is None:
            continue
        mapping[int(cid)] = src if src.get("chunk_text") else {**src, "chunk_text": src.get("snippet") or src.get("title") or ""}
    return mapping


def verify_row(sample: dict, payload: dict, verifier: GroundednessVerifier) -> ValidationRow:
    answer = payload.get("answer") or ""
    cbc = _contexts_by_citation(payload)
    result = verifier.verify(answer, cbc)
    return ValidationRow(
        id=sample["id"],
        question=sample["question"],
        groundedness=round(result.score, 3),
        citation_alignment=round(citation_alignment(answer, cbc), 3),
        unsupported_claim_rate=round(result.unsupported_claim_rate, 3),
        decision=result.decision,
        not_found=bool(payload.get("not_found")),
    )


def run_validation(samples: list[dict], *, generate, verifier: GroundednessVerifier) -> dict:
    rows: list[ValidationRow] = []
    for sample in samples:
        payload = generate(sample["question"])
        rows.append(verify_row(sample, payload, verifier))

    n = len(rows)
    answered = [r for r in rows if not r.not_found]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None
    return {
        "n": n,
        "n_answered": len(answered),
        "groundedness": mean([r.groundedness for r in answered]),
        "citation_alignment": mean([r.citation_alignment for r in answered]),
        "unsupported_claim_rate": mean([r.unsupported_claim_rate for r in answered]),
        "regenerate_rate": mean([1.0 if r.decision == DECISION_REGENERATE else 0.0 for r in rows]),
        "abstain_rate": mean([1.0 if r.decision == DECISION_ABSTAIN else 0.0 for r in rows]),
        "targets": {"groundedness": 0.95, "citation_alignment": 0.95, "unsupported_claim_rate": 0.02},
        "rows": [asdict(r) for r in rows],
    }


def _load_samples(limit: int) -> list[dict]:
    """Stratified answerable questions from the golden dataset (benchmark + faq)."""
    path = Path(__file__).resolve().parents[3] / "data" / "golden_dataset" / "golden_dataset.jsonl"
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["answerable"] and r["source_type"] in {"benchmark_seed", "official_faq"} and not r["synthetic"]:
            samples.append({"id": r["id"], "question": r["question"], "intent": r["intent"]})
    # round-robin by intent for a representative subset
    by_intent: dict[str, list] = {}
    for s in samples:
        by_intent.setdefault(s["intent"], []).append(s)
    out, i = [], 0
    while len(out) < limit and any(by_intent.values()):
        for intent in list(by_intent):
            if by_intent[intent] and len(out) < limit:
                out.append(by_intent[intent].pop())
        i += 1
        if i > 1000:
            break
    return out[:limit]


def main() -> None:
    import argparse

    from app.agent.umb_agent import run_umb_agent
    from app.core.config import get_settings
    from app.db.database import get_session_local
    from app.rag.answer_generator import build_default_entailment_checker, generate_answer
    from app.retrieval.intent_gate import detect_retrieval_intent

    ap = argparse.ArgumentParser(description="P4 mini groundedness validation")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()

    settings = get_settings()
    samples = _load_samples(args.limit)
    checker = build_default_entailment_checker(None)
    verifier = GroundednessVerifier(
        checker, checker_name=settings.cgcv_entailment_mode,
        return_threshold=settings.groundedness_return_threshold,
        regenerate_threshold=settings.groundedness_regenerate_threshold,
    )

    SessionLocal = get_session_local()

    def generate(question: str) -> dict:
        with SessionLocal() as db:
            agent = run_umb_agent(
                db=db, query=question, retrieval_mode="indexed", top_k=settings.rag_top_k_default,
                root_domain=settings.allowed_domain, match_query=question,
                intent=detect_retrieval_intent(question),
            )
            return generate_answer(question=question, contexts=agent.contexts, language="id")

    report = run_validation(samples, generate=generate, verifier=verifier)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"n={report['n']} answered={report['n_answered']} groundedness={report['groundedness']} "
          f"citation_alignment={report['citation_alignment']} unsupported={report['unsupported_claim_rate']} "
          f"regenerate={report['regenerate_rate']} abstain={report['abstain_rate']}")
    print(f"-> {_OUT}")


if __name__ == "__main__":
    main()
