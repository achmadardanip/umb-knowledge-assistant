from __future__ import annotations

from weakref import WeakKeyDictionary

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import Chunk, ChunkEmbedding, utcnow
from app.ingestion.embedder import BaseEmbedder

_SIDECAR_TABLE_READY: WeakKeyDictionary = WeakKeyDictionary()


def validate_embedding_batch(embedder: BaseEmbedder, vectors: list[list[float]], expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise RuntimeError(f"Embedding provider returned {len(vectors)} vectors for {expected_count} texts.")
    dimension = getattr(embedder, "dimension", None)
    if dimension is None:
        return
    for vector in vectors:
        if len(vector) != dimension:
            raise RuntimeError(f"Embedding dimension mismatch: expected {dimension}, got {len(vector)}.")


def stores_in_sidecar(embedder: BaseEmbedder) -> bool:
    return getattr(embedder, "storage", "legacy") == "sidecar"


def ensure_embedding_storage(db: Session, embedder: BaseEmbedder) -> None:
    if not stores_in_sidecar(embedder):
        return
    bind = db.get_bind()
    if _SIDECAR_TABLE_READY.get(bind):
        return
    # Inspect via the session's OWN connection — not inspect(engine), which opens a fresh
    # connection whose teardown issues a ROLLBACK. On a shared (StaticPool) SQLite
    # connection that rollback would undo the session's pending Source/Document flush
    # mid-transaction (chunk + sidecar persist, Source vanishes).
    if not inspect(db.connection()).has_table("chunk_embeddings"):
        raise RuntimeError(
            "The chunk_embeddings table is missing. Apply "
            "app/db/migrations/add_chunk_embeddings.sql before using local embeddings."
        )
    _SIDECAR_TABLE_READY[bind] = True


def store_chunk_embedding(db: Session, chunk: Chunk, vector: list[float], embedder: BaseEmbedder) -> None:
    if not stores_in_sidecar(embedder):
        chunk.embedding = vector
        return

    ensure_embedding_storage(db, embedder)
    profile = getattr(embedder, "profile", None)
    dimension = getattr(embedder, "dimension", None)
    if not profile or dimension != 384:
        raise RuntimeError("Sidecar embeddings require a named profile and dimension 384.")

    existing = next((item for item in chunk.embeddings if item.profile == profile), None)
    if existing is None and chunk.id:
        existing = (
            db.query(ChunkEmbedding)
            .filter(ChunkEmbedding.chunk_id == chunk.id, ChunkEmbedding.profile == profile)
            .first()
        )
    if existing is None:
        existing = ChunkEmbedding(chunk=chunk, profile=profile)
        db.add(existing)

    existing.provider = getattr(embedder, "provider_name", "unknown")
    existing.model = getattr(embedder, "model", "unknown")
    existing.dimension = dimension
    existing.version = getattr(embedder, "version", "1")
    existing.embedding = vector
    existing.updated_at = utcnow()
