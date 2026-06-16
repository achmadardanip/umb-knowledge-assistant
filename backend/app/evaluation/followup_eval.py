"""
P3 — conversation-state-isolation evaluator.

Measures, against ``followup_context_benchmark.json``, whether the production
follow-up logic isolates a new-topic turn from the previous turn's entity/topic
context. DB-free and deterministic: it drives the REAL production functions
(``analyze_followup`` + ``_build_retrieval_query`` + ``detect_retrieval_intent``),
including an assistant turn carrying source hints, so every leakage vector (prior
user turn, chat title, prior source hints) is exercised.

Metrics:
  followup_accuracy      — predicted is_followup == expected_followup
  intent_switch_accuracy — on real new-topic switches, the system correctly does
                           NOT treat the turn as a follow-up
  context_leakage_rate   — on new-topic turns, a distinctive prior-turn term still
                           appears in the turn-2 retrieval query

Targets: context_leakage_rate < 0.01, followup_accuracy > 0.95.

Run:  PYTHONPATH=. python -m app.evaluation.followup_eval
"""

from __future__ import annotations

import json
from pathlib import Path

_DATASET = Path(__file__).resolve().parent / "followup_context_benchmark.json"


def _history_for(q1: str, subject_title: str) -> list[dict]:
    """Turn-1 user message + an assistant answer that cites a source titled after the
    turn-1 subject — the strongest leakage vector for the turn-2 retrieval query."""
    return [
        {"role": "user", "content": q1},
        {
            "role": "assistant",
            "content": "Berikut informasinya [1].",
            "sources": [{
                "title": subject_title,
                "hostname": "mercubuana.ac.id",
                "url": "https://mercubuana.ac.id/" + subject_title.lower().replace(" ", "-"),
            }],
        },
    ]


def evaluate(cases: list[dict] | None = None) -> dict:
    from app.api.routes_chat import _build_retrieval_query
    from app.rag.intent_router import analyze_followup
    from app.retrieval.intent_gate import detect_retrieval_intent

    if cases is None:
        cases = json.loads(_DATASET.read_text(encoding="utf-8"))["conversations"]

    n = len(cases)
    followup_correct = 0
    switch_total = 0
    switch_correct = 0
    new_topic_total = 0
    leaked = 0
    leak_examples: list[dict] = []

    for case in cases:
        q1, q2 = case["turns"]
        title = case.get("chat_title")
        expected_followup = bool(case["expected_followup"])
        prior_terms = [t.lower() for t in case.get("prior_terms", [])]

        decision = analyze_followup(q2, [{"role": "user", "content": q1}])
        if decision.is_followup == expected_followup:
            followup_correct += 1

        # A real new-topic switch must be handled as NOT a follow-up.
        if not expected_followup:
            new_topic_total += 1
            switch_total += 1
            if not decision.is_followup:
                switch_correct += 1

            retrieval_intent = detect_retrieval_intent(q2)
            query = _build_retrieval_query(
                q2, _history_for(q1, title or q1), title,
                is_followup=decision.is_followup, intent=retrieval_intent,
            ).lower()
            hit = next((t for t in prior_terms if t and t in query), None)
            if hit:
                leaked += 1
                if len(leak_examples) < 20:
                    leak_examples.append({"id": case["id"], "q1": q1, "q2": q2, "leaked_term": hit})

    return {
        "n_conversations": n,
        "n_new_topic": new_topic_total,
        "n_followup": n - new_topic_total,
        "followup_accuracy": round(followup_correct / n, 4) if n else None,
        "intent_switch_accuracy": round(switch_correct / switch_total, 4) if switch_total else None,
        "context_leakage_rate": round(leaked / new_topic_total, 4) if new_topic_total else None,
        "leaked_count": leaked,
        "targets": {"context_leakage_rate": 0.01, "followup_accuracy": 0.95},
        "targets_met": {
            "context_leakage_rate": (leaked / new_topic_total) < 0.01 if new_topic_total else None,
            "followup_accuracy": (followup_correct / n) > 0.95 if n else None,
        },
        "leak_examples": leak_examples,
    }


def main() -> None:
    report = evaluate()
    out = Path(__file__).resolve().parents[3] / "reports" / "followup_isolation_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"conversations           : {report['n_conversations']} "
          f"({report['n_new_topic']} new-topic / {report['n_followup']} follow-up)")
    print(f"followup_accuracy       : {report['followup_accuracy']}  [target > 0.95]")
    print(f"intent_switch_accuracy  : {report['intent_switch_accuracy']}")
    print(f"context_leakage_rate    : {report['context_leakage_rate']}  [target < 0.01]  (leaked={report['leaked_count']})")
    print(f"targets_met             : {report['targets_met']}")
    print(f"report -> {out}")


if __name__ == "__main__":
    main()
