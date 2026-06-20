"""Phase 20 P20.2 — follow-up resolution benchmark v2 (with session memory).

Mirrors the production turn loop WITH the new session memory + follow-up resolver:

    ctx = memory.recall(sid)
    enriched = enrich_query(question, ctx)      # resolve elliptical via memory
    contexts = query_entities(db, enriched)
    memory.remember(sid, query=question, contexts=contexts, intent=...)

Sessions thread through several faculties/programs with anaphoric, subject-omitting
follow-ups ("Beliau menjabat sejak kapan?", "Bagaimana akreditasinya?", "Kalau yang
kelas karyawan?"). Measures context retention + follow-up resolution + leakage.

    python -m app.evaluation.followup_benchmark_v2 --out ../reports/conversation_reliability_report_v2.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from app.chat.session_memory import SessionMemory
from app.db.database import get_session_local
from app.db.models import UMBFaculty
from app.rag.followup_resolution import enrich_query, is_elliptical
from app.retrieval.entity_retriever import query_entities

_THREADS = [
    ("FEB", "Fakultas Ekonomi dan Bisnis", "Manajemen"),
    ("FASILKOM", "Fakultas Ilmu Komputer", "Sistem Informasi"),
    ("FT", "Fakultas Teknik", "Teknik Elektro"),
    ("FIKOM", "Fakultas Ilmu Komunikasi", "Penyiaran"),
    ("FDSK", "Fakultas Desain dan Seni Kreatif", "Desain Komunikasi Visual"),
    ("FPSI", "Fakultas Psikologi", "Psikologi"),
]
# Elliptical follow-ups (subject omitted -> must be resolved from memory).
_FAC_FU = ["Siapa dekannya?", "Beliau menjabat sejak kapan?", "Bagaimana akreditasinya?", "Di mana profilnya?"]
_PROG_FU = ["Siapa kaprodinya?", "Akreditasinya bagaimana?", "Kalau yang kelas karyawan?"]


def _faculty_of(ctx: dict, n2s: dict[str, str]) -> str | None:
    title = str(ctx.get("title") or "")
    for full, short in n2s.items():
        if full.lower() in title.lower():
            return short
    return None


def _make_session(turns: int) -> list[dict]:
    out: list[dict] = []
    i = 0
    while len(out) < turns:
        short, full, prog = _THREADS[i % len(_THREADS)]
        i += 1
        out.append({"q": f"Ceritakan tentang {full}", "exp": short, "kind": "establish"})
        for fu in _FAC_FU:
            if len(out) >= turns:
                break
            out.append({"q": fu, "exp": short, "kind": "fac_fu"})
        if len(out) >= turns:
            break
        out.append({"q": f"Bagaimana dengan program studi {prog}?", "exp": short, "kind": "prog"})
        for fu in _PROG_FU:
            if len(out) >= turns:
                break
            out.append({"q": fu, "exp": short, "kind": "prog_fu"})
    return out[:turns]


def _run(db, session, n2s) -> dict:
    mem = SessionMemory()
    sid = str(uuid.uuid4())
    total = retained = 0
    fus = fus_ok = 0
    leakage = 0
    for turn in session:
        q = turn["q"]
        ctx = mem.recall(sid)
        enriched = enrich_query(q, ctx)
        contexts = query_entities(db, enriched)
        top = contexts[0] if contexts else {}
        got = _faculty_of(top, n2s)
        ok = got == turn["exp"]
        total += 1
        retained += ok
        if turn["kind"].endswith("fu"):
            fus += 1
            fus_ok += ok
        leaked = {_faculty_of(c, n2s) for c in contexts[:3]} - {None, turn["exp"]}
        if leaked:
            leakage += 1
        mem.remember(sid, query=q, contexts=contexts, intent=turn["kind"])
    return {
        "turns": total,
        "context_retention": round(retained / max(total, 1), 4),
        "followups": fus,
        "followup_resolution": round(fus_ok / max(fus, 1), 4),
        "faculty_leakage": leakage,
        "entity_drift": round(1 - retained / max(total, 1), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/conversation_reliability_report_v2.json")
    args = ap.parse_args()
    db = get_session_local()()
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        sessions = {"A_10_turns": 10, "B_20_turns": 20, "C_50_turns": 50}
        results = {k: _run(db, _make_session(n), n2s) for k, n in sessions.items()}
    finally:
        db.close()

    ctx_ret = sum(r["context_retention"] for r in results.values()) / len(results)
    fu_res = sum(r["followup_resolution"] for r in results.values()) / len(results)
    leak = sum(r["faculty_leakage"] for r in results.values())
    drift = max(r["entity_drift"] for r in results.values())
    report = {
        "sessions": results,
        "aggregate": {"context_retention": round(ctx_ret, 4), "followup_resolution": round(fu_res, 4),
                      "faculty_leakage": leak, "max_entity_drift": round(drift, 4)},
        "success_criteria": {
            "context_retention>=0.95": ctx_ret >= 0.95,
            "followup_resolution>=0.95": fu_res >= 0.95,
            "faculty_leakage=0": leak == 0,
        },
        "with_session_memory": True,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, r in results.items():
        print(f"  {k}: retention={r['context_retention']} followup={r['followup_resolution']} leakage={r['faculty_leakage']}")
    print("aggregate:", report["aggregate"])
    print("success:", report["success_criteria"])


if __name__ == "__main__":
    main()
