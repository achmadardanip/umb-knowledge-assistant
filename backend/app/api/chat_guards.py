"""Pre-flight safety guards for the chat endpoints (OWASP LLM10 / LLM01).

Cheap checks applied before any retrieval or LLM work: input-size cap and
per-client rate limiting. Kept as small injectable functions so they are unit
tested without spinning up the HTTP stack.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.rate_limit import SlidingWindowRateLimiter, get_chat_rate_limiter


def enforce_question_length(question: str, max_chars: int) -> None:
    if len(question or "") > max_chars:
        raise HTTPException(status_code=413, detail="Pertanyaan terlalu panjang. / Question is too long.")


def enforce_rate_limit(limiter: SlidingWindowRateLimiter, key: str) -> None:
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Terlalu banyak permintaan, coba lagi nanti. / Too many requests, please slow down.",
        )


def _client_key(request, anonymous_session_id: str | None) -> str:
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or anonymous_session_id or "anonymous"


def apply_chat_safeguards(request, *, question: str, anonymous_session_id: str | None) -> None:
    settings = get_settings()
    enforce_question_length(question, settings.max_question_chars)
    if settings.rate_limit_enabled:
        enforce_rate_limit(get_chat_rate_limiter(), _client_key(request, anonymous_session_id))
