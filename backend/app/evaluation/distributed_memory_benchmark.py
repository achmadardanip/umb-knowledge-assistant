"""Phase 24 P24.4/P24.5 — distributed (Postgres-backed) session-memory benchmark.

Runs the multi-turn conversation benchmark through the PostgresProvider (shared DB
storage) at 10/20/50/100 turns, and simulates 2/4/8 separate "workers" (independent
provider instances pointed at the same DB) to prove memory is not lost across workers.

    python -m app.evaluation.distributed_memory_benchmark --out ../reports/distributed_memory_report.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from app.chat.memory_provider import PostgresProvider
from app.chat.session_memory import SessionContext
from app.db.database import get_session_local
from app.db.models import UMBFaculty
from app.rag.followup_resolution import enrich_query
from app.retrieval.entity_retriever import query_entities

_THREADS = [
    ("FEB", "Fakultas Ekonomi dan Bisnis", "Manajemen"),
    ("FASILKOM", "Fakultas Ilmu Komputer", "Sistem Informasi"),
    ("FT", "Fakultas Teknik", "Teknik Elektro"),
    ("FIKOM", "Fakultas Ilmu Komunikasi", "Penyiaran"),
    ("FDSK", "Fakultas Desain dan Seni Kreatif", "Desain Komunikasi Visual"),
    ("FPSI", "Fakultas Psikologi", "Psikologi"),
]
_FAC_FU = ["Siapa dekannya?", "Beliau menjabat sejak kapan?", "Bagaimana akreditasinya?"]
_PROG_FU = ["Siapa kaprodinya?", "Akreditasinya bagaimana?"]


def _faculty_of(ctx, n2s):
    t = str((ctx or {}).get("title") or "")
    for full, short in n2s.items():
        if full.lower() in t.lower():
            return short
    return None


def _make_session(turns):
    out, i = [], 0
    while len(out) < turns:
        short, full, prog = _THREADS[i % len(_THREADS)]; i += 1
        out.append({"q": f"Ceritakan tentang {full}", "exp": short})
        for fu in _FAC_FU:
            if len(out) >= turns: break
            out.append({"q": fu, "exp": short})
        if len(out) >= turns: break
        out.append({"q": f"Bagaimana dengan program studi {prog}?", "exp": short})
        for fu in _PROG_FU:
            if len(out) >= turns: break
            out.append({"q": fu, "exp": short})
    return out[:turns]


def _run_turns(db, provider, n2s, turns):
    sid = str(uuid.uuid4())
    total = retained = fus = fus_ok = 0
    for turn in _make_session(turns):
        ctx = provider.recall(sid, db)
        got = query_entities(db, enrich_query(turn["q"], ctx))
        ok = (_faculty_of(got[0], n2s) if got else None) == turn["exp"]
        total += 1; retained += ok
        if turn["q"] in _FAC_FU or turn["q"] in _PROG_FU:
            fus += 1; fus_ok += ok
        provider.remember(sid, query=turn["q"], contexts=got, intent="faculty", db=db)
    return {"turns": total, "context_retention": round(retained / max(total, 1), 4),
            "followup_resolution": round(fus_ok / max(fus, 1), 4)}


def _multiworker(db, n2s, workers):
    """Each 'worker' is an independent PostgresProvider instance on the same DB.
    Worker 0 establishes the subject; the others must recall it (no memory loss)."""
    sid = str(uuid.uuid4())
    provs = [PostgresProvider() for _ in range(workers)]
    est = "Ceritakan tentang Fakultas Ilmu Komputer"
    provs[0].remember(sid, query=est, contexts=query_entities(db, est), intent="faculty", db=db)
    seen = []
    for w in range(workers):
        ctx = provs[w].recall(sid, db)
        got = query_entities(db, enrich_query("Siapa dekannya?", ctx))
        seen.append(_faculty_of(got[0], n2s) if got else None)
    return {"workers": workers, "resolved": seen,
            "no_memory_loss": all(s == "FASILKOM" for s in seen)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/distributed_memory_report.json")
    args = ap.parse_args()
    db = get_session_local()()
    provider = PostgresProvider()
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        turn_results = {f"{n}_turns": _run_turns(db, provider, n2s, n) for n in (10, 20, 50, 100)}
        worker_results = {f"{w}_workers": _multiworker(db, n2s, w) for w in (2, 4, 8)}
    finally:
        db.close()

    min_ret = min(r["context_retention"] for r in turn_results.values())
    min_fu = min(r["followup_resolution"] for r in turn_results.values())
    all_workers_ok = all(r["no_memory_loss"] for r in worker_results.values())
    report = {
        "backend": "PostgresProvider (chat_memories, shared across workers)",
        "turn_benchmarks": turn_results,
        "multiworker": worker_results,
        "success_criteria": {
            "context_retention=1.0": min_ret == 1.0,
            "followup_resolution=1.0": min_fu == 1.0,
            "no_memory_loss_across_workers": all_workers_ok,
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, r in turn_results.items():
        print(f"  {k}: retention={r['context_retention']} followup={r['followup_resolution']}")
    for k, r in worker_results.items():
        print(f"  {k}: resolved={r['resolved']} no_loss={r['no_memory_loss']}")
    print("success:", report["success_criteria"])


if __name__ == "__main__":
    main()
