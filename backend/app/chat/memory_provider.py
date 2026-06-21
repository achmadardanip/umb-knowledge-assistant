"""Phase 24 — pluggable session-memory storage (removes the single-worker limit).

    MemoryProvider
      ├── InMemoryProvider   (process-local TTL+LRU — fast, single-worker)
      └── PostgresProvider   (chat_memories table — shared across workers)

Both share the SAME entity-extraction logic (`session_memory.apply_turn`) so the
multi-turn behaviour is identical; only the storage differs. Selected by
``SESSION_MEMORY_BACKEND`` (memory | postgres). Default = memory (preserves the
certified single-worker behaviour + benchmark).
"""

from __future__ import annotations

import os
import time
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chat.session_memory import (
    SessionContext,
    apply_turn,
    get_session_memory,
)

# Entity slots persisted per session (P24.3: faculty/program/dean/kaprodi/accreditation/service).
_KEYS = ("faculty", "faculty_short", "program", "dean", "kaprodi",
         "accreditation_subject", "service", "topic")
_TTL_SECONDS = 30 * 60


class MemoryProvider(Protocol):
    def recall(self, session_id: str | None, db: Session | None = None) -> SessionContext | None: ...
    def remember(self, session_id: str | None, *, query: str = "", contexts: list[dict] | None = None,
                 intent: str | None = None, db: Session | None = None) -> SessionContext | None: ...
    def clear(self, session_id: str | None, db: Session | None = None) -> None: ...


class InMemoryProvider:
    """Wraps the existing in-process SessionMemory singleton."""

    def __init__(self) -> None:
        self._mem = get_session_memory()

    def recall(self, session_id, db=None):
        return self._mem.recall(session_id)

    def remember(self, session_id, *, query="", contexts=None, intent=None, db=None):
        return self._mem.remember(session_id, query=query, contexts=contexts, intent=intent)

    def clear(self, session_id, db=None):
        self._mem.clear(session_id)


class PostgresProvider:
    """Persists the session entity context to chat_memories (one row per slot),
    keyed by the string session id in ``anonymous_session_id`` (no FK), so any
    worker reads the same memory. Idempotent upsert; TTL via expires_at."""

    def __init__(self, ttl: int = _TTL_SECONDS) -> None:
        self._ttl = ttl
        self._fallback = get_session_memory()  # used if no db session is available

    def _with_db(self, db: Session | None):
        if db is not None:
            return db, False
        from app.db.database import get_session_local
        return get_session_local()(), True

    def recall(self, session_id, db=None):
        if not session_id:
            return None
        conn, owned = self._with_db(db)
        try:
            rows = conn.execute(text(
                "SELECT memory_key, memory_value FROM chat_memories "
                "WHERE anonymous_session_id = :sid AND memory_type = 'recurring_context' AND memory_key LIKE 'se:%' "
                "AND is_active = true AND (expires_at IS NULL OR expires_at > now())"
            ), {"sid": str(session_id)}).all()
        except Exception:
            return None
        finally:
            if owned:
                conn.close()
        if not rows:
            return None
        ctx = SessionContext()
        for k, v in rows:
            slot = k[3:] if k and k.startswith('se:') else k
            if slot in _KEYS and v is not None:
                setattr(ctx, slot, v)
        ctx.updated_at = time.time()
        return ctx

    def remember(self, session_id, *, query="", contexts=None, intent=None, db=None):
        if not session_id:
            return None
        ctx = self.recall(session_id, db) or SessionContext()
        apply_turn(ctx, query=query, contexts=contexts, intent=intent)
        conn, owned = self._with_db(db)
        try:
            sid = str(session_id)
            conn.execute(text(
                "UPDATE chat_memories SET is_active = false "
                "WHERE anonymous_session_id = :sid AND memory_type = 'recurring_context' AND memory_key LIKE 'se:%'"
            ), {"sid": sid})
            for key in _KEYS:
                val = getattr(ctx, key, None)
                if val is None:
                    continue
                conn.execute(text(
                    "INSERT INTO chat_memories "
                    "  (id, anonymous_session_id, memory_type, memory_key, memory_value, "
                    "   content, importance_score, is_active, created_at, updated_at, expires_at) "
                    "VALUES (gen_random_uuid(), :sid, 'recurring_context', 'se:' || :k, :v, :v, 0.9, true, "
                    "        now(), now(), now() + (:ttl || ' seconds')::interval)"
                ), {"sid": sid, "k": key, "v": str(val), "ttl": self._ttl})
            conn.commit()
        except Exception:
            conn.rollback()
            # graceful degradation: keep an in-process copy so the turn still works
            fb = self._fallback.recall(sid) or SessionContext()
            apply_turn(fb, query=query, contexts=contexts, intent=intent)
            self._fallback._store[sid] = fb  # type: ignore[attr-defined]
        finally:
            if owned:
                conn.close()
        return ctx

    def clear(self, session_id, db=None):
        if not session_id:
            return
        conn, owned = self._with_db(db)
        try:
            conn.execute(text(
                "UPDATE chat_memories SET is_active = false "
                "WHERE anonymous_session_id = :sid AND memory_type = 'recurring_context' AND memory_key LIKE 'se:%'"
            ), {"sid": str(session_id)})
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            if owned:
                conn.close()


_PROVIDER: MemoryProvider | None = None


def get_memory_provider() -> MemoryProvider:
    global _PROVIDER
    if _PROVIDER is None:
        backend = os.getenv("SESSION_MEMORY_BACKEND", "memory").strip().lower()
        _PROVIDER = PostgresProvider() if backend == "postgres" else InMemoryProvider()
    return _PROVIDER


def reset_memory_provider() -> None:  # for tests/benchmarks
    global _PROVIDER
    _PROVIDER = None
