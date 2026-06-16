"""
v3 P6 — migrate data from Supabase to a local Postgres (pgvector).

Copies sources, documents, chunks, embeddings, structured entities, FAQs,
canonical URLs and the discovery cache from the SOURCE DB (Supabase) into the
TARGET local DB. Idempotent (ON CONFLICT DO NOTHING by primary key). The graph
artifacts (``data/graph/*.json``) are plain files — copy them with the repo.

Usage (from backend/):
    # source defaults to SUPABASE_POOLER_DATABASE_URL / DATABASE_URL,
    # target defaults to LOCAL_POSTGRES_URL.
    PYTHONPATH=. .venv/Scripts/python.exe -m app.db.supabase_to_local \
        [--source <url>] [--target <url>] [--batch 500]

Prereq: run ``python -m app.db.bootstrap_local`` against the target first.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import create_engine, text

from app.db.database import normalize_database_url

logger = logging.getLogger(__name__)

# Dependency order (parents before children for FK integrity).
TABLES: tuple[str, ...] = (
    "sources",
    "documents",
    "source_assets",
    "extracted_segments",
    "chunks",
    "chunk_embeddings",
    "umb_faculties",
    "umb_study_programs",
    "umb_campuses",
    "umb_scholarships",
    "umb_contacts",
    "umb_services",
    "umb_faqs",
    "canonical_urls",
    "knowledge_discovery_cache",
)

# Tables with a pgvector column needing an explicit ::text / ::vector cast.
# (chunks.embedding is a legacy 3072-dim column in prod — NOT used by retrieval, which
#  reads the 384-dim chunk_embeddings table — so it is skipped, not cast, below.)
_VECTOR_COLUMNS = {"chunk_embeddings": "embedding"}

# Columns omitted from the copy (→ NULL/default): the legacy 3072-dim chunks.embedding
# (dimension mismatch) and FK columns pointing at tables outside the retrieval set
# (documents/source_assets/segments) — retrieval only needs chunks→sources + embeddings.
_COLUMN_SKIP: dict[str, set[str]] = {
    "chunks": {"embedding", "document_id", "asset_id", "segment_id"},
}


def _columns(engine, table: str) -> list[str]:
    from sqlalchemy import inspect

    return [c["name"] for c in inspect(engine).get_columns(table)]


def _json_columns(engine, table: str) -> set[str]:
    """Target columns whose type is JSON/JSONB — these must transfer as text so
    psycopg3 doesn't try to adapt a Python dict/list (the 'cannot adapt type dict'
    failure), and also handles prod array columns mapped to a local JSON column."""
    from sqlalchemy import inspect

    out: set[str] = set()
    for c in inspect(engine).get_columns(table):
        if "JSON" in str(c["type"]).upper():
            out.add(c["name"])
    return out


def _copy_table(source_engine, target_engine, table: str, batch: int) -> dict:
    cols = _columns(target_engine, table)
    if not cols:
        return {"table": table, "skipped": "missing on target"}
    skip = _COLUMN_SKIP.get(table, set())
    cols = [c for c in cols if c not in skip]
    vec = _VECTOR_COLUMNS.get(table)
    json_cols = _json_columns(target_engine, table)

    def _sel(c: str) -> str:
        if c == vec:
            return f"{c}::text AS {c}"  # vector → text
        if c in json_cols:
            return f"to_jsonb({c})::text AS {c}"  # jsonb/json/array → canonical JSON text
        return c

    def _ph(c: str) -> str:
        if c == vec:
            return f"CAST(:{c} AS vector(384))"
        if c in json_cols:
            return f"CAST(:{c} AS jsonb)"
        return f":{c}"

    # SELECT — JSON/vector columns transfer as plain text strings.
    select_cols = ", ".join(_sel(c) for c in cols)
    # INSERT — cast text back to its real type; ON CONFLICT keeps it idempotent.
    insert_cols = ", ".join(cols)
    placeholders = ", ".join(_ph(c) for c in cols)
    insert_sql = text(
        f"INSERT INTO {table} ({insert_cols}) VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )

    copied = 0
    with source_engine.connect() as src:
        result = src.execution_options(stream_results=True).execute(text(f"SELECT {select_cols} FROM {table}"))
        while True:
            rows = result.fetchmany(batch)
            if not rows:
                break
            payload = [dict(r._mapping) for r in rows]
            with target_engine.begin() as dst:
                dst.execute(insert_sql, payload)
            copied += len(payload)
            logger.info("  %s: +%s (total %s)", table, len(payload), copied)
    return {"table": table, "copied": copied}


def migrate(source_url: str, target_url: str, *, batch: int = 500) -> list[dict]:
    source_engine = create_engine(normalize_database_url(source_url), pool_pre_ping=True,
                                  connect_args={"prepare_threshold": None})
    target_engine = create_engine(normalize_database_url(target_url), pool_pre_ping=True)
    report: list[dict] = []
    try:
        for table in TABLES:
            try:
                report.append(_copy_table(source_engine, target_engine, table, batch))
            except Exception as exc:
                logger.warning("table %s failed: %s", table, exc)
                report.append({"table": table, "error": str(exc)[:200]})
    finally:
        source_engine.dispose()
        target_engine.dispose()
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.config import get_settings

    settings = get_settings()
    import os

    ap = argparse.ArgumentParser(description="Migrate Supabase data to local Postgres")
    ap.add_argument("--source", default=os.getenv("SUPABASE_POOLER_DATABASE_URL") or os.getenv("DATABASE_URL"))
    ap.add_argument("--target", default=settings.local_postgres_url)
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()
    if not args.source:
        raise SystemExit("No --source DB URL (set SUPABASE_POOLER_DATABASE_URL).")
    logger.info("Migrating %s -> %s", args.source.split("@")[-1], args.target.split("@")[-1])
    report = migrate(args.source, args.target, batch=args.batch)
    total = sum(r.get("copied", 0) for r in report)
    logger.info("Done. %s rows across %s tables.", total, len(report))
    for r in report:
        logger.info("  %s", r)


if __name__ == "__main__":
    main()
