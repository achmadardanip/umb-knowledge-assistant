"""Dense (semantic) retrieval over chunk embeddings.

Brute-force cosine is used here: it is correct, dependency-free, and runs on the
SQLite dev/test database. In production on PostgreSQL, the pgvector HNSW index
(``ORDER BY embedding <=> :q LIMIT k``) replaces the scan — same contract, ANN
speed. Scope is enforced per row so a poisoned/out-of-scope embedding can never
surface (LLM08).
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from app.db.models import Chunk, Source
from app.discovery.scope_validator import is_allowed_host, validate_url_scope


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def dense_search(
    db: Session,
    query_embedding: list[float],
    *,
    top_k: int = 5,
    root_domain: str = "mercubuana.ac.id",
    source_types: list[str] | None = None,
) -> list[dict]:
    if not query_embedding:
        return []
    query = db.query(Chunk, Source).join(Source, Chunk.source_id == Source.id).filter(Source.status == "indexed")
    if source_types:
        query = query.filter(Chunk.source_type.in_(source_types))

    scored: list[tuple[float, Chunk, Source, str, str, dict]] = []
    for chunk, source in query.all():
        embedding = chunk.embedding
        if not embedding:
            continue
        meta = chunk.meta or {}
        url = meta.get("url") or (source.url if source else None)
        hostname = meta.get("hostname") or (source.hostname if source else None)
        if not url or not is_allowed_host(hostname, root_domain) or not validate_url_scope(url, root_domain).is_allowed:
            continue
        scored.append((cosine_similarity(query_embedding, embedding), chunk, source, url, hostname, meta))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict] = []
    for similarity, chunk, source, url, hostname, meta in scored[:top_k]:
        results.append(
            {
                "chunk_id": chunk.id,
                "source_id": chunk.source_id,
                "asset_id": chunk.asset_id,
                "segment_id": chunk.segment_id,
                "chunk_text": chunk.chunk_text,
                "url": url,
                "title": meta.get("title") or (source.title if source else None),
                "score": similarity,
                "hostname": hostname,
                "discovery_source": meta.get("discovery_source") or (source.discovery_source if source else None),
                "source_type": chunk.source_type or meta.get("source_type"),
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
            }
        )
    return results
