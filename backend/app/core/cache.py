"""
v3 P5 — shared cache layer (egress reduction).

A small unified cache used to avoid repeated Supabase reads on the hot path:
FAQ rows → entity lookups → retrieval results. In-process TTL+LRU by default
(zero dependencies); a Redis backend is used automatically when ``REDIS_URL`` is
configured and ``redis`` is importable.

Cache order (most → least cacheable): FAQ, Entity, Graph (already file-cached),
Retrieval. Keys are namespaced; values may be arbitrary Python objects
(in-process) or pickled (Redis).
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import threading
import time
from collections import OrderedDict
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 2048


class _InProcessCache:
    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries

    def get(self, key: str):
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expiry, value = item
            if expiry < now:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class _RedisCache:
    def __init__(self, client):
        self._r = client

    def get(self, key: str):
        raw = self._r.get(key)
        return pickle.loads(raw) if raw is not None else None

    def set(self, key: str, value: Any, ttl: float) -> None:
        self._r.set(key, pickle.dumps(value), ex=int(max(1, ttl)))

    def clear(self) -> None:
        try:
            self._r.flushdb()
        except Exception:
            pass


_BACKEND = None
_BACKEND_LOCK = threading.Lock()


def _backend():
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    with _BACKEND_LOCK:
        if _BACKEND is not None:
            return _BACKEND
        url = getattr(get_settings(), "redis_url", None)
        if url:
            try:
                import redis  # type: ignore

                client = redis.Redis.from_url(url, socket_connect_timeout=2)
                client.ping()
                _BACKEND = _RedisCache(client)
                logger.info("Cache backend: Redis (%s)", url.split("@")[-1])
                return _BACKEND
            except Exception as exc:
                logger.warning("Redis unavailable (%s); falling back to in-process cache.", exc)
        _BACKEND = _InProcessCache()
        return _BACKEND


def make_key(namespace: str, *parts) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
    return f"umb:{namespace}:{digest}"


def cache_enabled() -> bool:
    return bool(getattr(get_settings(), "cache_enabled", True))


def cache_get(key: str):
    if not cache_enabled():
        return None
    try:
        return _backend().get(key)
    except Exception as exc:
        logger.debug("cache_get failed: %s", exc)
        return None


def cache_set(key: str, value, ttl: float | None = None) -> None:
    if not cache_enabled():
        return
    try:
        _backend().set(key, value, ttl if ttl is not None else float(getattr(get_settings(), "cache_ttl_seconds", 300)))
    except Exception as exc:
        logger.debug("cache_set failed: %s", exc)


def cache_clear() -> None:
    try:
        _backend().clear()
    except Exception:
        pass


def reset_backend_for_tests() -> None:
    global _BACKEND
    _BACKEND = None
