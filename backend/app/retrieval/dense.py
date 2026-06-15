"""Dense retrieval over legacy vectors or a profile-aware pgvector sidecar."""

from __future__ import annotations

import json
import math
from weakref import WeakKeyDictionary

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, defer

from app.db.models import Chunk, ChunkEmbedding, Source
from app.discovery.scope_validator import is_allowed_host, validate_url_scope

_SIDECAR_TABLE_READY: WeakKeyDictionary = WeakKeyDictionary()


def _has_sidecar_table(db: Session) -> bool:
    bind = db.get_bind()
    if _SIDECAR_TABLE_READY.get(bind):
        return True
    ready = inspect(db.connection()).has_table("chunk_embeddings")
    if ready:
        _SIDECAR_TABLE_READY[bind] = True
    return ready


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        raise ValueError(f"Cannot compare embeddings with different dimensions: {len(a)} != {len(b)}.")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _context(chunk: Chunk, source: Source, similarity: float) -> dict | None:
    meta = chunk.meta or {}
    url = meta.get("url") or source.url
    hostname = meta.get("hostname") or source.hostname
    if not url:
        return None
    return {
        "chunk_id": chunk.id,
        "source_id": chunk.source_id,
        "asset_id": chunk.asset_id,
        "segment_id": chunk.segment_id,
        "chunk_text": chunk.chunk_text,
        "url": url,
        "title": meta.get("title") or source.title,
        "score": similarity,
        "hostname": hostname,
        "discovery_source": meta.get("discovery_source") or source.discovery_source,
        "source_type": chunk.source_type or meta.get("source_type"),
        "page_type": meta.get("page_type"),
        "content_type": meta.get("content_type"),
        "media_type": meta.get("media_type"),
        "page_number": chunk.page_number or meta.get("page_number"),
        "slide_number": chunk.slide_number or meta.get("slide_number"),
        "sheet_name": chunk.sheet_name or meta.get("sheet_name"),
        "row_range": chunk.row_range or meta.get("row_range"),
        "timestamp_start": chunk.timestamp_start or meta.get("timestamp_start"),
        "timestamp_end": chunk.timestamp_end or meta.get("timestamp_end"),
        "extraction_method": chunk.extraction_method or meta.get("extraction_method"),
        "extraction_confidence": chunk.extraction_confidence
        if chunk.extraction_confidence is not None
        else meta.get("extraction_confidence"),
        "fetched_at": source.fetched_at,
    }


def _postgres_profile_candidates(
    db: Session,
    query_embedding: list[float],
    *,
    profile: str,
    candidate_limit: int,
    source_types: list[str] | None,
) -> list[tuple[float, Chunk, Source]]:
    clauses = ["ce.profile = :profile", "s.status = 'indexed'"]
    params: dict = {
        "profile": profile,
        "query_embedding": json.dumps(query_embedding),
        "candidate_limit": candidate_limit,
    }
    if source_types:
        placeholders = []
        for index, source_type in enumerate(source_types):
            key = f"source_type_{index}"
            placeholders.append(f":{key}")
            params[key] = source_type
        clauses.append(f"c.source_type IN ({', '.join(placeholders)})")
    statement = text(
        f"""
        SELECT ce.chunk_id,
               1 - (ce.embedding <=> CAST(:query_embedding AS vector(384))) AS similarity
        FROM chunk_embeddings AS ce
        JOIN chunks AS c ON c.id = ce.chunk_id
        JOIN sources AS s ON s.id = c.source_id
        WHERE {' AND '.join(clauses)}
        ORDER BY ce.embedding <=> CAST(:query_embedding AS vector(384))
        LIMIT :candidate_limit
        """
    )
    rows = db.execute(statement, params).all()
    if not rows:
        return []
    rank = {str(row.chunk_id): (index, float(row.similarity)) for index, row in enumerate(rows)}
    joined = (
        db.query(Chunk, Source)
        .options(defer(Chunk.embedding))  # v3 P5: never transfer the legacy vector
        .join(Source, Chunk.source_id == Source.id)
        .filter(Chunk.id.in_(list(rank)))
        .all()
    )
    candidates = [(rank[str(chunk.id)][1], chunk, source) for chunk, source in joined]
    candidates.sort(key=lambda item: rank[str(item[1].id)][0])
    return candidates


def dense_search(
    db: Session,
    query_embedding: list[float],
    *,
    top_k: int = 5,
    root_domain: str = "mercubuana.ac.id",
    source_types: list[str] | None = None,
    embedding_profile: str | None = None,
) -> list[dict]:
    if not query_embedding:
        return []
    if embedding_profile and len(query_embedding) != 384:
        raise ValueError(
            f"Embedding profile {embedding_profile!r} requires a 384-dimensional query vector; "
            f"got {len(query_embedding)}."
        )

    candidate_limit = max(top_k * 4, 20)
    if embedding_profile:
        if not _has_sidecar_table(db):
            return []
        if db.get_bind().dialect.name == "postgresql":
            scored = _postgres_profile_candidates(
                db,
                query_embedding,
                profile=embedding_profile,
                candidate_limit=candidate_limit,
                source_types=source_types,
            )
        else:
            query = (
                db.query(ChunkEmbedding, Chunk, Source)
                .join(Chunk, ChunkEmbedding.chunk_id == Chunk.id)
                .join(Source, Chunk.source_id == Source.id)
                .filter(ChunkEmbedding.profile == embedding_profile, Source.status == "indexed")
            )
            if source_types:
                query = query.filter(Chunk.source_type.in_(source_types))
            scored = [
                (cosine_similarity(query_embedding, item.embedding), chunk, source)
                for item, chunk, source in query.all()
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            scored = scored[:candidate_limit]
    else:
        query = db.query(Chunk, Source).join(Source, Chunk.source_id == Source.id).filter(Source.status == "indexed")
        if source_types:
            query = query.filter(Chunk.source_type.in_(source_types))
        scored = []
        for chunk, source in query.all():
            if chunk.embedding:
                scored.append((cosine_similarity(query_embedding, chunk.embedding), chunk, source))
        scored.sort(key=lambda item: item[0], reverse=True)

    results: list[dict] = []
    for similarity, chunk, source in scored:
        context = _context(chunk, source, similarity)
        if context is None:
            continue
        if not is_allowed_host(context["hostname"], root_domain):
            continue
        if not validate_url_scope(context["url"], root_domain).is_allowed:
            continue
        results.append(context)
        if len(results) >= top_k:
            break
    return results
