"""
v3 P5 — chunk metadata pruning (egress + storage reduction).

The audit found ``chunks.metadata`` averaging ~13 KB/row (max 82 KB), dominated by
EPrints/repository junk the retriever never reads: ``links`` (avg ~30 KB), full
``DC.description`` / ``eprints.abstract`` thesis abstracts, ``images``, and dozens
of ``DC.*`` / ``eprints.*`` keys. Every retrieval loaded ~200 candidate rows × this
bloat → the dominant Supabase egress driver.

The retriever / ``_context`` / ``RetrievedContext`` only read the small fields in
``CHUNK_META_KEEP``. ``prune_all_chunks`` rewrites metadata to that allowlist
*server-side* (no egress for the rewrite); ``prune_metadata`` is applied to new
chunks at ingest so they never re-bloat.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# The only metadata keys the retrieval/answer path reads (everything else is dead
# weight). Most are also columns on ``chunks``; these are kept as fallbacks.
CHUNK_META_KEEP: frozenset[str] = frozenset({
    "url", "hostname", "title", "path",
    "source_type", "content_type", "media_type", "page_type",
    "discovery_source", "ingested_via", "extraction_method", "extraction_confidence",
    "page_number", "slide_number", "sheet_name", "row_range",
    "timestamp_start", "timestamp_end", "language", "chunk_index", "priority",
})


def prune_metadata(meta: dict | None) -> dict:
    """Keep only the allowlisted keys."""
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items() if k in CHUNK_META_KEEP}


def prune_all_chunks(db: Session, *, min_len: int = 600) -> dict:
    """Rewrite bloated chunks.metadata to the allowlist, entirely server-side.

    Only touches rows whose serialized metadata exceeds ``min_len`` chars. Returns
    counts + before/after average size. Postgres only (uses jsonb functions)."""
    if db.get_bind().dialect.name != "postgresql":
        return {"skipped": "non-postgresql backend"}

    keep = sorted(CHUNK_META_KEEP)
    before = db.execute(text("SELECT count(*), round(avg(length(metadata::text))) FROM chunks WHERE metadata IS NOT NULL")).fetchone()
    bloated = db.execute(
        text("SELECT count(*) FROM chunks WHERE metadata IS NOT NULL AND length(metadata::text) > :n"),
        {"n": min_len},
    ).scalar()

    result = db.execute(
        text(
            """
            UPDATE chunks
            SET metadata = COALESCE((
                SELECT jsonb_object_agg(kv.key, kv.value)
                FROM jsonb_each(metadata) AS kv
                WHERE kv.key = ANY(:keep)
            ), '{}'::jsonb)
            WHERE metadata IS NOT NULL AND length(metadata::text) > :n
            """
        ),
        {"keep": keep, "n": min_len},
    )
    db.commit()
    after = db.execute(text("SELECT count(*), round(avg(length(metadata::text))) FROM chunks WHERE metadata IS NOT NULL")).fetchone()
    return {
        "rows_pruned": result.rowcount,
        "rows_bloated_before": bloated,
        "avg_meta_chars_before": float(before[1]) if before and before[1] is not None else None,
        "avg_meta_chars_after": float(after[1]) if after and after[1] is not None else None,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.db.database import get_session_local

    db = get_session_local()()
    try:
        result = prune_all_chunks(db)
        logger.info("chunk metadata prune: %s", result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
