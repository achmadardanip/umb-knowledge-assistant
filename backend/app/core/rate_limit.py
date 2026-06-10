"""In-memory sliding-window rate limiter (OWASP LLM10 — unbounded consumption).

Single-instance, dependency-free, and thread-safe. For multi-instance
deployments back this with Redis (the ``allow`` contract stays the same).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from functools import lru_cache
from typing import Callable

from app.core.config import get_settings


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record a request for ``key`` and return whether it is within budget."""
        with self._lock:
            now = self._clock()
            events = self._events[key]
            cutoff = now - self._window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._max_requests:
                return False
            events.append(now)
            return True


@lru_cache(maxsize=1)
def get_chat_rate_limiter() -> SlidingWindowRateLimiter:
    settings = get_settings()
    return SlidingWindowRateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
