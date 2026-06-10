"""In-memory UMB knowledge graph: entity co-occurrence + entity->chunk index.

GraphRAG core. Built from (chunk_id, text) pairs with the LLM-free extractor:
  * nodes        = UMB entities
  * edges        = co-occurrence within the same chunk (weight = #chunks)
  * entity_chunks= which chunks mention each entity (the retrieval index)

``related_chunk_ids`` powers relation-aware / multi-hop retrieval: it takes the
query's entities, walks one hop along the strongest edges, and returns chunk ids
ranked by how many of those (query + neighbour) entities they mention. Serialisable
to/from a plain dict for JSON persistence and incremental rebuilds.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from app.graph.entities import extract_entities

_QUERY_WEIGHT = 2.0
_NEIGHBOR_WEIGHT = 1.0


class KnowledgeGraph:
    def __init__(self) -> None:
        self._entity_chunks: dict[str, set[str]] = defaultdict(set)
        self._adj: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # --- build -----------------------------------------------------------
    def add_chunk(self, chunk_id: str, text: str, *, max_entities: int | None = None) -> None:
        entities = list(dict.fromkeys(extract_entities(text)))  # unique, ordered
        if max_entities is not None:
            entities = entities[:max_entities]
        for entity in entities:
            self._entity_chunks[entity].add(chunk_id)
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                a, b = entities[i], entities[j]
                self._adj[a][b] += 1
                self._adj[b][a] += 1

    # --- query -----------------------------------------------------------
    def chunks_for_entity(self, entity: str) -> set[str]:
        return set(self._entity_chunks.get(entity, set()))

    def neighbors(self, entity: str, *, limit: int | None = None) -> list[str]:
        ranked = sorted(self._adj.get(entity, {}).items(), key=lambda kv: (-kv[1], kv[0]))
        names = [name for name, _ in ranked]
        return names[:limit] if limit is not None else names

    def related_chunk_ids(self, query_text: str, *, limit: int = 10, neighbor_limit: int = 5) -> list[str]:
        query_entities = list(dict.fromkeys(extract_entities(query_text)))
        if not query_entities:
            return []
        relevant: dict[str, float] = {}
        for entity in query_entities:
            relevant[entity] = _QUERY_WEIGHT
            for neighbor in self.neighbors(entity, limit=neighbor_limit):
                relevant.setdefault(neighbor, _NEIGHBOR_WEIGHT)
        scores: dict[str, float] = defaultdict(float)
        for entity, weight in relevant.items():
            for chunk_id in self._entity_chunks.get(entity, ()):  # type: ignore[arg-type]
                scores[chunk_id] += weight
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return [chunk_id for chunk_id, _ in ranked][:limit]

    def prune(self, *, min_chunks: int = 2, protected: set[str] | frozenset[str] = frozenset()) -> None:
        """Drop noise: entities appearing in < min_chunks chunks (unless protected),
        and clean up any edges that referenced them."""
        remove = {
            entity
            for entity, chunks in self._entity_chunks.items()
            if len(chunks) < min_chunks and entity not in protected
        }
        if not remove:
            return
        for entity in remove:
            self._entity_chunks.pop(entity, None)
            self._adj.pop(entity, None)
        for neighbors in self._adj.values():
            for entity in remove:
                neighbors.pop(entity, None)

    @property
    def entity_count(self) -> int:
        return len(self._entity_chunks)

    # --- persistence -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "entity_chunks": {entity: sorted(chunks) for entity, chunks in self._entity_chunks.items()},
            "adj": {entity: dict(neighbors) for entity, neighbors in self._adj.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeGraph":
        graph = cls()
        for entity, chunks in (data.get("entity_chunks") or {}).items():
            graph._entity_chunks[entity] = set(chunks)
        for entity, neighbors in (data.get("adj") or {}).items():
            graph._adj[entity] = defaultdict(int, {k: int(v) for k, v in neighbors.items()})
        return graph


def build_graph(chunks: Iterable[tuple[str, str]], *, max_entities_per_chunk: int | None = None) -> KnowledgeGraph:
    graph = KnowledgeGraph()
    for chunk_id, text in chunks:
        graph.add_chunk(chunk_id, text, max_entities=max_entities_per_chunk)
    return graph
