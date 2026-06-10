"""DB build + JSON persistence + retrieval bridge for the UMB knowledge graph.

  * ``build_graph_from_db`` walks indexed chunks and builds the co-occurrence graph.
  * ``save_graph`` / ``load_graph`` persist to JSON (mtime-cached load) so the graph
    is rebuilt incrementally by a scheduled job, not on every request.
  * ``expansion_contexts`` turns the graph's related chunk ids into contexts in the
    exact ``RetrievedContext`` shape, so they merge with keyword/dense/web contexts
    and flow through the same generation + citation pipeline.
"""

from __future__ import annotations

import json
import logging
import os

from sqlalchemy.orm import Session

from app.db.models import Chunk, Source
from app.discovery.scope_validator import is_allowed_host, validate_url_scope
from app.graph.entities import GAZETTEER_SET
from app.graph.graph_index import KnowledgeGraph
from app.retrieval.hybrid_retriever import RetrievedContext

logger = logging.getLogger(__name__)

_GRAPH_EXPAND_ORIGIN = "graph_expand"
_BASE_SCORE = 0.5
_SCORE_STEP = 0.03
_MIN_SCORE = 0.2

# path -> (mtime, graph)
_CACHE: dict[str, tuple[float, KnowledgeGraph]] = {}


def build_graph_from_db(db: Session, *, max_entities_per_chunk: int = 25, min_entity_chunks: int = 2) -> KnowledgeGraph:
    graph = KnowledgeGraph()
    rows = (
        db.query(Chunk.id, Chunk.chunk_text)
        .join(Source, Chunk.source_id == Source.id)
        .filter(Source.status == "indexed")
        .yield_per(500)
    )
    for chunk_id, text in rows:
        graph.add_chunk(str(chunk_id), text or "", max_entities=max_entities_per_chunk)
    # Drop one-off acronym noise (keep gazetteer entities always) to bound size.
    graph.prune(min_chunks=min_entity_chunks, protected=GAZETTEER_SET)
    return graph


def save_graph(graph: KnowledgeGraph, path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(graph.to_dict(), handle, ensure_ascii=False)
    _CACHE.pop(path, None)


def load_graph(path: str) -> KnowledgeGraph | None:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            graph = KnowledgeGraph.from_dict(json.load(handle))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load knowledge graph %s: %s", path, exc)
        return None
    _CACHE[path] = (mtime, graph)
    return graph


def expansion_contexts(
    db: Session,
    query: str,
    graph: KnowledgeGraph,
    *,
    root_domain: str,
    limit: int,
    exclude_chunk_ids: set[str] | None = None,
) -> list[dict]:
    """Return graph-expanded contexts (retriever shape) for the query's entities."""
    exclude = exclude_chunk_ids or set()
    related = [cid for cid in graph.related_chunk_ids(query, limit=limit * 3) if cid not in exclude]
    if not related:
        return []
    rows = (
        db.query(Chunk, Source)
        .join(Source, Chunk.source_id == Source.id)
        .filter(Chunk.id.in_(related), Source.status == "indexed")
        .all()
    )
    by_id = {str(chunk.id): (chunk, source) for chunk, source in rows}

    contexts: list[dict] = []
    for chunk_id in related:  # preserve graph ranking
        pair = by_id.get(chunk_id)
        if pair is None:
            continue
        chunk, source = pair
        meta = chunk.meta or {}
        url = meta.get("url") or (source.url if source else None)
        hostname = meta.get("hostname") or (source.hostname if source else None)
        if not url or not is_allowed_host(hostname, root_domain) or not validate_url_scope(url, root_domain).is_allowed:
            continue
        score = max(_MIN_SCORE, _BASE_SCORE - _SCORE_STEP * len(contexts))
        contexts.append(
            RetrievedContext(
                chunk_id=str(chunk.id),
                source_id=chunk.source_id,
                asset_id=chunk.asset_id,
                segment_id=chunk.segment_id,
                chunk_text=chunk.chunk_text,
                url=url,
                title=meta.get("title") or (source.title if source else None),
                score=score,
                hostname=hostname,
                discovery_source=_GRAPH_EXPAND_ORIGIN,
                source_type=chunk.source_type or meta.get("source_type"),
                page_type=meta.get("page_type"),
                content_type=meta.get("content_type"),
                media_type=meta.get("media_type"),
                page_number=chunk.page_number or meta.get("page_number"),
                slide_number=chunk.slide_number or meta.get("slide_number"),
                sheet_name=chunk.sheet_name or meta.get("sheet_name"),
                row_range=chunk.row_range or meta.get("row_range"),
                timestamp_start=chunk.timestamp_start or meta.get("timestamp_start"),
                timestamp_end=chunk.timestamp_end or meta.get("timestamp_end"),
                extraction_method=chunk.extraction_method or meta.get("extraction_method"),
                extraction_confidence=chunk.extraction_confidence
                if chunk.extraction_confidence is not None
                else meta.get("extraction_confidence"),
                fetched_at=getattr(source, "fetched_at", None),
            ).as_dict()
        )
        if len(contexts) >= limit:
            break
    return contexts
