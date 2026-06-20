"""Phase 16 P16.4 — stale-content audit.

Buckets every source/chunk by crawl age (fresh ≤30d, aging 31-180d, stale >180d)
and flags stale faculty / accreditation pages so maintenance can target them.

    python -m app.evaluation.stale_content_audit --out ../reports/freshness_audit.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.db.database import get_session_local
from app.rag.freshness import AGING_MAX_DAYS, FRESH_MAX_DAYS

_FACULTY_HOSTS = ("feb.", "ft.", "fasilkom.", "fikom.", "fdsk.", "psikologi.", "pascasarjana.", "fakultas.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/freshness_audit.json")
    args = ap.parse_args()

    db = get_session_local()()
    s = lambda q, **kw: db.execute(text(q), kw).scalar()
    try:
        age = "EXTRACT(DAY FROM now() - fetched_at)"
        total = s("SELECT count(*) FROM sources")
        with_date = s("SELECT count(*) FROM sources WHERE fetched_at IS NOT NULL")
        fresh = s(f"SELECT count(*) FROM sources WHERE {age} <= :a", a=FRESH_MAX_DAYS)
        aging = s(f"SELECT count(*) FROM sources WHERE {age} > :a AND {age} <= :b", a=FRESH_MAX_DAYS, b=AGING_MAX_DAYS)
        stale = s(f"SELECT count(*) FROM sources WHERE {age} > :b", b=AGING_MAX_DAYS)
        oldest = s("SELECT min(fetched_at) FROM sources")
        newest = s("SELECT max(fetched_at) FROM sources")

        chunk_age = "EXTRACT(DAY FROM now() - s.fetched_at)"
        stale_chunks = s(
            f"SELECT count(*) FROM chunks c JOIN sources s ON c.source_id=s.id WHERE {chunk_age} > :b",
            b=AGING_MAX_DAYS,
        )
        total_chunks = s("SELECT count(*) FROM chunks")

        fac_clause = " OR ".join(f"s.hostname ILIKE '{h}%'" for h in _FACULTY_HOSTS)
        stale_faculty = s(
            f"SELECT count(*) FROM sources s WHERE ({fac_clause}) AND {age.replace('fetched_at','s.fetched_at')} > :b",
            b=AGING_MAX_DAYS,
        )
        stale_accreditation = s(
            f"SELECT count(*) FROM sources s WHERE (s.url ILIKE '%akreditas%' OR s.title ILIKE '%akreditas%' "
            f"OR s.url ILIKE '%ban-pt%') AND {age.replace('fetched_at','s.fetched_at')} > :b",
            b=AGING_MAX_DAYS,
        )

        # provenance coverage — every source exposes a crawl date.
        freshness_metadata_pct = round(100 * with_date / max(total, 1), 2)

        report = {
            "thresholds": {"fresh_max_days": FRESH_MAX_DAYS, "aging_max_days": AGING_MAX_DAYS},
            "total_sources": total,
            "sources_with_crawl_date": with_date,
            "freshness_metadata_pct": freshness_metadata_pct,
            "fresh_sources": fresh,
            "aging_sources": aging,
            "stale_sources": stale,
            "total_chunks": total_chunks,
            "stale_chunks": stale_chunks,
            "stale_faculty_pages": stale_faculty,
            "stale_accreditation_pages": stale_accreditation,
            "oldest_crawl": oldest.isoformat() if oldest else None,
            "newest_crawl": newest.isoformat() if newest else None,
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k in ("total_sources", "freshness_metadata_pct", "fresh_sources", "aging_sources",
              "stale_sources", "stale_chunks", "stale_faculty_pages", "stale_accreditation_pages"):
        print(f"  {k}: {report[k]}")


if __name__ == "__main__":
    main()
