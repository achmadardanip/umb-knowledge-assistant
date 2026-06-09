"""Embedding-keyed semantic answer cache (cost optimization).

Returns a cached answer when a new query is semantically near a previously
answered one (cosine >= threshold), so paraphrases ("berapa biaya kuliah?" vs
"berapa uang kuliahnya?") are served without another retrieval + LLM call — the
primary $/query lever. This is the in-memory lookup core; production persists the
(embedding, payload) entries in Redis or pgvector and does the nearest-neighbour
search there with the same contract.
"""

from __future__ import annotations

from app.retrieval.dense import cosine_similarity


class SemanticCache:
    def __init__(self, *, threshold: float = 0.92) -> None:
        self._threshold = threshold
        self._entries: list[tuple[list[float], dict]] = []

    def get(self, query_embedding: list[float]) -> dict | None:
        best_payload: dict | None = None
        best_similarity = 0.0
        for embedding, payload in self._entries:
            try:
                similarity = cosine_similarity(query_embedding, embedding)
            except ValueError:
                continue
            if similarity > best_similarity:
                best_similarity = similarity
                best_payload = payload
        if best_payload is not None and best_similarity >= self._threshold:
            return best_payload
        return None

    def put(self, query_embedding: list[float], payload: dict) -> None:
        self._entries.append((query_embedding, payload))
