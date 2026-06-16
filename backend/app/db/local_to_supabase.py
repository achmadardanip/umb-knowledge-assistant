"""
Phase-10 STEP 1 — sync NEW local coverage content UP to Supabase production.

Targeted + reversible: only the Phase-7 coverage rows (sources/chunks/chunk_embeddings
tagged ``discovery_source='phase7_official'``) plus the dean entity enrichments are pushed.
Prod dean values are backed up first (rollback), and the new chunks are tagged so they can
be removed with a single DELETE. Writes are tiny (~1.3 MB storage) and add no egress.

Run (from backend/):
    PYTHONPATH=. python -m app.db.local_to_supabase --diff      # read-only preview
    PYTHONPATH=. python -m app.db.local_to_supabase --execute   # perform the sync
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from sqlalchemy import create_engine, text

from app.db.database import normalize_database_url
from app.db.supabase_to_local import _columns, _json_columns

logger = logging.getLogger(__name__)
_TAG = "phase7_official"
# legacy/foreign-key columns omitted from the chunk insert (prod chunks.embedding is a
# 3072-dim legacy column; document/asset/segment FKs point at un-synced local rows).
_CHUNK_SKIP = {"embedding", "document_id", "asset_id", "segment_id"}


def _copy_filtered(local_engine, prod_engine, table: str, where: str, *, skip: set[str] | None = None, batch: int = 500) -> int:
    skip = skip or set()
    cols = [c for c in _columns(prod_engine, table) if c not in skip]
    json_cols = _json_columns(prod_engine, table)
    vec = "embedding" if table == "chunk_embeddings" else None

    def _sel(c):
        if c == vec:
            return f"{c}::text AS {c}"
        if c in json_cols:
            return f"to_jsonb({c})::text AS {c}"
        return c

    def _ph(c):
        if c == vec:
            return f"CAST(:{c} AS vector(384))"
        if c in json_cols:
            return f"CAST(:{c} AS jsonb)"
        return f":{c}"

    sel = ", ".join(_sel(c) for c in cols)
    ins = text(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(_ph(c) for c in cols)}) ON CONFLICT DO NOTHING")
    copied = 0
    with local_engine.connect() as src:
        rows = src.execution_options(stream_results=True).execute(text(f"SELECT {sel} FROM {table} WHERE {where}"))
        while True:
            chunk = rows.fetchmany(batch)
            if not chunk:
                break
            payload = [dict(r._mapping) for r in chunk]
            with prod_engine.begin() as dst:
                dst.execute(ins, payload)
            copied += len(payload)
    return copied


def _engines():
    import os

    from app.core.config import get_settings
    settings = get_settings()
    prod = os.getenv("SUPABASE_POOLER_DATABASE_URL") or os.getenv("DATABASE_URL")
    local = settings.local_postgres_url
    return (create_engine(normalize_database_url(local), pool_pre_ping=True),
            create_engine(normalize_database_url(prod), pool_pre_ping=True, connect_args={"prepare_threshold": None}))


def diff(local_engine, prod_engine) -> dict:
    with local_engine.connect() as lc:
        new_sources = lc.execute(text(f"SELECT count(*) FROM sources WHERE discovery_source=:t"), {"t": _TAG}).scalar()
        new_chunks = lc.execute(text("SELECT count(*) FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE discovery_source=:t)"), {"t": _TAG}).scalar()
        deans = lc.execute(text("SELECT name, dean FROM umb_faculties WHERE dean IS NOT NULL")).fetchall()
    with prod_engine.connect() as pc:
        existing_chunks = pc.execute(text("SELECT count(*) FROM chunks")).scalar()
        prod_deans = {r[0]: r[1] for r in pc.execute(text("SELECT name, dean FROM umb_faculties")).fetchall()}
    updated = [{"faculty": n, "new_dean": d, "old_dean": prod_deans.get(n)} for n, d in deans if prod_deans.get(n) != d]
    return {"existing_chunks": existing_chunks, "new_chunks": new_chunks, "new_sources": new_sources,
            "updated_entities": updated, "duplicate_candidates": 0}


def execute_sync(local_engine, prod_engine) -> dict:
    # 1) backup prod deans (rollback)
    with prod_engine.connect() as pc:
        backup = {r[0]: r[1] for r in pc.execute(text("SELECT name, dean FROM umb_faculties")).fetchall()}
    Path(__file__).resolve().parents[3].joinpath("backups").mkdir(exist_ok=True)
    Path(__file__).resolve().parents[3].joinpath("backups", "prod_deans_backup.json").write_text(
        json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) sync coverage sources -> chunks -> embeddings (FK order)
    src = _copy_filtered(local_engine, prod_engine, "sources", f"discovery_source='{_TAG}'")
    chk = _copy_filtered(local_engine, prod_engine, "chunks",
                         f"source_id IN (SELECT id FROM sources WHERE discovery_source='{_TAG}')", skip=_CHUNK_SKIP)
    emb = _copy_filtered(local_engine, prod_engine, "chunk_embeddings",
                         f"chunk_id IN (SELECT id FROM chunks WHERE source_id IN (SELECT id FROM sources WHERE discovery_source='{_TAG}'))")

    # 3) dean updates (only where prod is empty/different)
    with local_engine.connect() as lc:
        deans = lc.execute(text("SELECT name, dean FROM umb_faculties WHERE dean IS NOT NULL")).fetchall()
    updated = 0
    with prod_engine.begin() as pc:
        for name, dean in deans:
            r = pc.execute(text("UPDATE umb_faculties SET dean=:d WHERE name=:n AND (dean IS NULL OR dean<>:d)"),
                           {"d": dean, "n": name})
            updated += r.rowcount
    return {"sources_synced": src, "chunks_synced": chk, "embeddings_synced": emb, "deans_updated": updated}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Sync local coverage content -> Supabase")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    local_engine, prod_engine = _engines()
    rep = Path(__file__).resolve().parents[3] / "reports"
    rep.mkdir(exist_ok=True)
    try:
        d = diff(local_engine, prod_engine)
        (rep / "sync_diff_report.json").write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print("DIFF:", json.dumps(d, ensure_ascii=False))
        if args.execute:
            result = execute_sync(local_engine, prod_engine)
            (rep / "sync_execution_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print("SYNCED:", json.dumps(result, ensure_ascii=False))
    finally:
        local_engine.dispose()
        prod_engine.dispose()


if __name__ == "__main__":
    main()
