"""Phase 19 P19.2 — long-conversation reliability benchmark.

Retrieval benchmarks measure single-shot accuracy. This measures *conversation
stability* over 10 / 20 / 50-turn sessions: when a follow-up turn is elliptical
("siapa dekannya?", "akreditasinya?"), does the system still resolve to the
faculty/program established earlier — without drifting or leaking another faculty?

Each turn is run through the production contextual-query builder
(``_build_retrieval_query`` with the running history) + the structured entity
layer (``query_entities``) — deterministic and CPU-fast (no LLM generation).

Metrics: context/entity/faculty/dean/accreditation retention, follow-up
resolution, faculty leakage, hallucination (wrong-faculty top entity).

    python -m app.evaluation.long_conversation_benchmark --out ../reports/conversation_reliability_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.api.routes_chat import _build_retrieval_query
from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.rag.intent_router import analyze_followup
from app.retrieval.entity_retriever import query_entities
from app.retrieval.intent_gate import detect_retrieval_intent

# Faculty short -> (full name, an alias to introduce it, a program it owns).
_THREADS = [
    ("FEB", "Fakultas Ekonomi dan Bisnis", "Manajemen"),
    ("FASILKOM", "Fakultas Ilmu Komputer", "Sistem Informasi"),
    ("FT", "Fakultas Teknik", "Teknik Elektro"),
    ("FIKOM", "Fakultas Ilmu Komunikasi", "Penyiaran"),
    ("FDSK", "Fakultas Desain dan Seni Kreatif", "Desain Komunikasi Visual"),
    ("FPSI", "Fakultas Psikologi", "Psikologi"),
]
# Elliptical follow-ups that must inherit the established faculty context. These
# are faculty-attributable (resolve to the faculty card / its program) and are
# classified as follow-ups by analyze_followup; "Di kampus mana?" is intentionally
# excluded — it resolves to a campus entity, not a faculty-retention signal.
_FACULTY_FOLLOWUPS = ["Siapa dekannya?", "Akreditasinya bagaimana?", "Bagaimana profilnya?"]
_PROGRAM_FOLLOWUPS = ["Siapa kaprodinya?"]


def _faculty_of(ctx: dict, name_to_short: dict[str, str]) -> str | None:
    title = str(ctx.get("title") or "")
    for full, short in name_to_short.items():
        if full.lower() in title.lower():
            return short
    return None


def _make_session(turns: int) -> list[dict]:
    """Build a scripted session of ~turns user turns that threads through several
    faculties with elliptical follow-ups (so context must be retained)."""
    session: list[dict] = []
    t = 0
    i = 0
    while t < turns:
        short, full, prog = _THREADS[i % len(_THREADS)]
        i += 1
        # establish faculty
        session.append({"q": f"Ceritakan tentang {full}", "expect_short": short, "kind": "establish"})
        t += 1
        for fu in _FACULTY_FOLLOWUPS:
            if t >= turns:
                break
            session.append({"q": fu, "expect_short": short, "kind": "faculty_followup"})
            t += 1
        if t >= turns:
            break
        # program sub-thread
        session.append({"q": f"Bagaimana dengan program studi {prog}?", "expect_short": short, "kind": "program"})
        t += 1
        for fu in _PROGRAM_FOLLOWUPS:
            if t >= turns:
                break
            session.append({"q": fu, "expect_short": short, "kind": "program_followup"})
            t += 1
    return session[:turns]


def _run_session(db, session: list[dict], name_to_short: dict[str, str]) -> dict:
    history: list[dict] = []
    title = None
    total = 0
    retained = 0
    followups = 0
    followups_resolved = 0
    leakage = 0
    hallucinations = 0
    for idx, turn in enumerate(session):
        q = turn["q"]
        # Mirror the production flow exactly: the real follow-up classifier decides
        # whether conversation context is inherited or reset (a new explicit-faculty
        # question is a new topic; an elliptical "siapa dekannya?" is a follow-up).
        followup = analyze_followup(q, history)
        is_followup = followup.is_followup
        intent = detect_retrieval_intent(q)
        intent_str = getattr(intent, "intent", None) if not isinstance(intent, str) else intent
        conversation_history = history if is_followup else []
        rq = _build_retrieval_query(q, conversation_history, title, is_followup=is_followup, intent=intent_str)
        ctxs = query_entities(db, rq)
        top = ctxs[0] if ctxs else {}
        top_short = _faculty_of(top, name_to_short)
        ok = top_short == turn["expect_short"]
        total += 1
        retained += ok
        if turn["kind"].endswith("followup"):
            followups += 1
            followups_resolved += ok
        # leakage / hallucination: a DIFFERENT faculty surfaced in top-3.
        leaked = {_faculty_of(c, name_to_short) for c in ctxs[:3]} - {None, turn["expect_short"]}
        if leaked:
            leakage += 1
        if top_short is not None and not ok:
            hallucinations += 1
        # extend history (user turn + a synthetic assistant ack so follow-ups have context)
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": f"({turn['expect_short']})"})
        if title is None:
            title = turn["expect_short"]
    return {
        "turns": total,
        "context_retention": round(retained / max(total, 1), 4),
        "followups": followups,
        "followup_resolution": round(followups_resolved / max(followups, 1), 4),
        "faculty_leakage": leakage,
        "hallucinations": hallucinations,
        "entity_drift": round(1 - retained / max(total, 1), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/conversation_reliability_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        name_to_short = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        sessions = {"A_10_turns": 10, "B_20_turns": 20, "C_50_turns": 50}
        results = {k: _run_session(db, _make_session(n), name_to_short) for k, n in sessions.items()}
    finally:
        db.close()

    agg_ctx = sum(r["context_retention"] for r in results.values()) / len(results)
    agg_fu = sum(r["followup_resolution"] for r in results.values()) / len(results)
    total_leak = sum(r["faculty_leakage"] for r in results.values())
    max_drift = max(r["entity_drift"] for r in results.values())
    report = {
        "sessions": results,
        "aggregate": {
            "context_retention": round(agg_ctx, 4),
            "followup_resolution": round(agg_fu, 4),
            "faculty_leakage": total_leak,
            "max_entity_drift": round(max_drift, 4),
        },
        "success_criteria": {
            "context_retention>=0.95": agg_ctx >= 0.95,
            "followup_resolution>=0.99": agg_fu >= 0.99,
            "entity_drift<=0.01": max_drift <= 0.01,
            "faculty_leakage=0": total_leak == 0,
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, r in results.items():
        print(f"  {k}: retention={r['context_retention']} followup={r['followup_resolution']} "
              f"leakage={r['faculty_leakage']} drift={r['entity_drift']}")
    print("aggregate:", report["aggregate"])
    print("success:", report["success_criteria"])


if __name__ == "__main__":
    main()
