"""Backfill dense embeddings for indexed chunks that lack them.

Run once after enabling dense retrieval, and incrementally as new chunks are
indexed. Embeddings come from the configured embedder (managed BGE-M3/OpenAI now,
self-hosted TEI later) — the model is swappable without touching this code.

    python -m app.ingestion.embed_backfill --batch-size 64
"""

from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from app.db.database import get_session_local
from app.db.models import Chunk
from app.ingestion.embedder import BaseEmbedder, get_embedder


def backfill_embeddings(db: Session, embedder: BaseEmbedder | None = None, *, batch_size: int = 64, limit: int | None = None) -> int:
    embedder = embedder or get_embedder()
    query = db.query(Chunk).filter(Chunk.embedding.is_(None))
    if limit is not None:
        query = query.limit(limit)
    chunks = query.all()
    populated = 0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors = embedder.embed_texts([chunk.chunk_text for chunk in batch])
        for chunk, vector in zip(batch, vectors):
            chunk.embedding = vector
            populated += 1
        db.commit()
    return populated


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill chunk embeddings for dense retrieval")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    with get_session_local()() as db:
        populated = backfill_embeddings(db, batch_size=args.batch_size, limit=args.limit)
    print(f"Backfilled {populated} chunk embeddings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
