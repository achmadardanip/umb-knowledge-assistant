"""Phase 16/17 — backward-compatible freshness + crawl-registry migration.

Idempotent. Adds the Phase-16 freshness columns to ``sources`` (nullable, so the
existing 11k rows stay valid and lose no provenance), backfills them from the
canonical ``fetched_at`` crawl timestamp, creates the Phase-17 ``crawl_registry``
table and seeds it from the current ``sources`` so change detection has a baseline.

    python -m app.db.migrate_freshness            # apply + report
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Critical domains crawled daily; everything else weekly. (Phase 17 P17.3/4.)
_CRITICAL_HOSTS = (
    "pendaftaran.mercubuana.ac.id", "baa.mercubuana.ac.id", "www.mercubuana.ac.id",
    "mercubuana.ac.id", "pmb.mercubuana.ac.id",
)

_FRESHNESS_COLUMNS = (
    "extraction_date", "source_last_modified", "pdf_modified_date",
    "first_seen_date", "last_verified_date",
)


def migrate(engine=None) -> dict:
    from app.db.database import get_engine
    from app.db.models import Base

    engine = engine or get_engine()
    if engine.dialect.name != "postgresql":
        return {"skipped": f"non-postgresql backend ({engine.dialect.name})"}

    # 1) additive freshness columns on sources.
    for col in _FRESHNESS_COLUMNS:
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE sources ADD COLUMN IF NOT EXISTS {col} timestamptz"))

    # 2) backfill from fetched_at (the canonical crawl_date) — only where null, so
    #    re-runs never clobber real values.
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE sources SET "
            "  first_seen_date = COALESCE(first_seen_date, fetched_at), "
            "  last_verified_date = COALESCE(last_verified_date, fetched_at), "
            "  extraction_date = COALESCE(extraction_date, fetched_at) "
            "WHERE fetched_at IS NOT NULL"
        ))

    # 3) crawl_registry table (ORM) + seed from sources.
    Base.metadata.create_all(engine, checkfirst=True)
    crit = ", ".join(f"'{h}'" for h in _CRITICAL_HOSTS)
    with engine.begin() as conn:
        seeded = conn.execute(text(
            "INSERT INTO crawl_registry "
            "  (id, url, hostname, content_hash, content_type, last_crawl, "
            "   last_modified, crawl_status, http_status, crawl_frequency, failure_count, created_at, updated_at) "
            "SELECT s.id, s.url, s.hostname, s.content_hash, "
            "       CASE WHEN s.url ILIKE '%.pdf' THEN 'pdf' ELSE 'html' END, "
            "       s.fetched_at, s.source_last_modified, "
            "       CASE WHEN s.status IS NULL THEN 'crawled' ELSE 'crawled' END, "
            "       s.http_status, "
            f"      CASE WHEN s.hostname IN ({crit}) THEN 'daily' ELSE 'weekly' END, "
            "       0, now(), now() "
            "FROM sources s "
            "ON CONFLICT (url) DO NOTHING"
        )).rowcount

    with engine.begin() as conn:
        counts = {
            "sources": conn.execute(text("SELECT count(*) FROM sources")).scalar(),
            "sources_with_first_seen": conn.execute(text("SELECT count(*) FROM sources WHERE first_seen_date IS NOT NULL")).scalar(),
            "crawl_registry": conn.execute(text("SELECT count(*) FROM crawl_registry")).scalar(),
            "registry_daily": conn.execute(text("SELECT count(*) FROM crawl_registry WHERE crawl_frequency='daily'")).scalar(),
        }
    counts["seeded_now"] = seeded
    return counts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = migrate()
    logger.info("freshness/crawl migration complete: %s", result)
    print(result)


if __name__ == "__main__":
    main()
