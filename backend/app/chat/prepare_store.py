"""Short-lived server-side store for deferred (browser-LLM) generations.

The Puter.js path splits a turn into prepare -> browser generate -> finalize. The
official contexts retrieved during prepare are kept here (NOT sent to and trusted
back from the client) so finalize verifies the browser answer against the same
server-vetted sources. TTL-pruned; single-process (fine for the local deployment).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class PreparedGeneration:
    session_id: str
    raw_question: str
    contexts: list[dict]
    language: str
    intent: str
    retrieval_mode: str
    memory_used: bool
    top_k: int
    indexed_context_count: int
    web_context_count: int
    agent_tool_calls: int
    visible_steps: list[dict]
    created_at: float = field(default_factory=time.time)


class PrepareStore:
    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, PreparedGeneration] = {}

    def put(self, prepared: PreparedGeneration) -> str:
        self._prune()
        key = uuid.uuid4().hex
        self._items[key] = prepared
        return key

    def get(self, key: str) -> PreparedGeneration | None:
        self._prune()
        return self._items.get(key)

    def pop(self, key: str) -> PreparedGeneration | None:
        self._prune()
        return self._items.pop(key, None)

    def _prune(self) -> None:
        cutoff = time.time() - self._ttl
        for key in [key for key, value in self._items.items() if value.created_at < cutoff]:
            self._items.pop(key, None)


prepare_store = PrepareStore()
