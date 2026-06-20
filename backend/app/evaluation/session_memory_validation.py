"""Phase 20 P20.1 — session entity memory validation.

Validates the memory store mechanics (entity extraction, per-session scoping,
TTL auto-expiry) and the resulting multi-turn context retention.

    python -m app.evaluation.session_memory_validation --out ../reports/session_memory_validation.json
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from app.chat.session_memory import SessionMemory
from app.db.database import get_session_local
from app.db.models import UMBFaculty
from app.rag.followup_resolution import enrich_query
from app.retrieval.entity_retriever import query_entities


def _faculty_of(ctx: dict, n2s: dict[str, str]) -> str | None:
    title = str(ctx.get("title") or "")
    for full, short in n2s.items():
        if full.lower() in title.lower():
            return short
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/session_memory_validation.json")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}

        # (1) entity extraction: establish FEB, then resolve an anaphoric follow-up.
        mem = SessionMemory()
        sid = str(uuid.uuid4())
        feb = query_entities(db, "Ceritakan tentang Fakultas Ekonomi dan Bisnis")
        mem.remember(sid, query="Ceritakan tentang Fakultas Ekonomi dan Bisnis", contexts=feb, intent="faculty")
        ctx = mem.recall(sid)
        extracted_faculty = ctx.faculty_short if ctx else None
        extracted_dean = bool(ctx and ctx.dean)
        # anaphoric follow-up resolves to FEB via memory
        fu_q = "Beliau menjabat sejak kapan?"
        enriched = enrich_query(fu_q, ctx)
        fu_top = query_entities(db, enriched)
        fu_resolved = _faculty_of(fu_top[0], n2s) if fu_top else None

        # (2) per-session scoping: a second session must not see the first's entity.
        sid2 = str(uuid.uuid4())
        scoping_ok = mem.recall(sid2) is None and mem.recall(sid) is not None

        # (3) TTL auto-expiry.
        short_mem = SessionMemory(ttl=1)
        s3 = str(uuid.uuid4())
        short_mem.remember(s3, query="Fakultas Teknik", contexts=[], intent="faculty")
        present_before = short_mem.recall(s3) is not None
        time.sleep(1.2)
        expired_after = short_mem.recall(s3) is None

        # (4) retention over a multi-faculty session with anaphoric follow-ups.
        threads = [("FEB", "Fakultas Ekonomi dan Bisnis"), ("FASILKOM", "Fakultas Ilmu Komputer"),
                   ("FT", "Fakultas Teknik"), ("FIKOM", "Fakultas Ilmu Komunikasi")]
        fus = ["Siapa dekannya?", "Beliau menjabat sejak kapan?", "Bagaimana akreditasinya?"]
        rmem = SessionMemory()
        rsid = str(uuid.uuid4())
        total = retained = 0
        for short, full in threads:
            for q in [f"Ceritakan tentang {full}", *fus]:
                c = rmem.recall(rsid)
                got = query_entities(db, enrich_query(q, c))
                ok = (_faculty_of(got[0], n2s) if got else None) == short
                total += 1
                retained += ok
                rmem.remember(rsid, query=q, contexts=got, intent="faculty")
        retention = round(retained / max(total, 1), 4)

        assertions = {
            "faculty_extracted": extracted_faculty == "FEB",
            "dean_extracted": extracted_dean,
            "anaphora_resolved_to_FEB": fu_resolved == "FEB",
            "per_session_scoping": scoping_ok,
            "ttl_present_before_expiry": present_before,
            "ttl_expired_after_ttl": expired_after,
            "context_retention>=0.95": retention >= 0.95,
        }
        report = {
            "extracted": {"faculty": extracted_faculty, "dean_present": extracted_dean,
                          "anaphora_follow_up_resolved": fu_resolved},
            "context_retention": retention,
            "turns": total,
            "assertions": assertions,
            "all_pass": all(assertions.values()),
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("context_retention:", report["context_retention"], "| all_pass:", report["all_pass"])
    print("assertions:", report["assertions"])


if __name__ == "__main__":
    main()
