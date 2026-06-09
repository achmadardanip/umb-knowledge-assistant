"""Backfill dense embeddings for indexed chunks that lack the active profile.

Run once after enabling dense retrieval, and incrementally as new chunks are
indexed. Legacy cloud embeddings remain in ``chunks.embedding``. Local E5
embeddings are written to the profile-aware ``chunk_embeddings`` sidecar table.

    python -m app.ingestion.embed_backfill --dry-run --only-keyword-only
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import and_, case, exists, func
from sqlalchemy.orm import Session

from app.db.database import get_session_local
from app.db.models import Chunk, ChunkEmbedding
from app.ingestion.embedder import BaseEmbedder, get_embedder
from app.ingestion.embedding_store import (
    ensure_embedding_storage,
    store_chunk_embedding,
    stores_in_sidecar,
    validate_embedding_batch,
)


def _candidate_query(db: Session, embedder: BaseEmbedder, *, only_keyword_only: bool):
    query = db.query(Chunk)
    if stores_in_sidecar(embedder):
        profile = getattr(embedder, "profile", None)
        if not profile:
            raise RuntimeError("Sidecar embedding backfill requires a named embedding profile.")
        already_embedded = exists().where(
            and_(
                ChunkEmbedding.chunk_id == Chunk.id,
                ChunkEmbedding.profile == profile,
                ChunkEmbedding.provider == getattr(embedder, "provider_name", "unknown"),
                ChunkEmbedding.model == getattr(embedder, "model", "unknown"),
                ChunkEmbedding.dimension == getattr(embedder, "dimension", None),
                ChunkEmbedding.version == getattr(embedder, "version", "1"),
            )
        )
        query = query.filter(~already_embedded)
    else:
        query = query.filter(Chunk.embedding.is_(None))

    if only_keyword_only:
        keyword_only_sources = (
            db.query(Chunk.source_id)
            .filter(Chunk.source_id.is_not(None))
            .group_by(Chunk.source_id)
            .having(func.sum(case((Chunk.embedding.is_not(None), 1), else_=0)) == 0)
        )
        query = query.filter(Chunk.source_id.in_(keyword_only_sources))

    return query.order_by(Chunk.created_at.asc(), Chunk.id.asc())


def backfill_embeddings(
    db: Session,
    embedder: BaseEmbedder | None = None,
    *,
    batch_size: int = 64,
    limit: int | None = None,
    dry_run: bool = False,
    only_keyword_only: bool = False,
) -> int:
    embedder = embedder or get_embedder()
    ensure_embedding_storage(db, embedder)
    query = _candidate_query(db, embedder, only_keyword_only=only_keyword_only)
    if limit is not None:
        query = query.limit(limit)
    chunks = query.all()
    if dry_run:
        return len(chunks)

    populated = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = None
        for attempt in range(5):
            try:
                vectors = embedder.embed_texts([chunk.chunk_text for chunk in batch])
                break
            except Exception:
                if attempt == 4:
                    db.commit()  # persist progress before giving up
                    raise
                time.sleep(30 * (attempt + 1))  # wait out the rate-limit window
        validate_embedding_batch(embedder, vectors, len(batch))
        for chunk, vector in zip(batch, vectors, strict=True):
            store_chunk_embedding(db, chunk, vector, embedder)
            populated += 1
        db.commit()
    return populated


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill chunk embeddings for dense retrieval")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Count matching chunks without embedding or writing")
    parser.add_argument(
        "--only-keyword-only",
        action="store_true",
        help="Only process sources where every legacy chunks.embedding value is NULL",
    )
    args = parser.parse_args()
    with get_session_local()() as db:
        populated = backfill_embeddings(
            db,
            batch_size=max(1, args.batch_size),
            limit=args.limit,
            dry_run=args.dry_run,
            only_keyword_only=args.only_keyword_only,
        )
    action = "Would backfill" if args.dry_run else "Backfilled"
    print(f"{action} {populated} chunk embeddings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
