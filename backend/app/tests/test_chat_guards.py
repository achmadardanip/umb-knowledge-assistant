import pytest
from fastapi import HTTPException

from app.api.chat_guards import enforce_question_length, enforce_rate_limit
from app.core.rate_limit import SlidingWindowRateLimiter


def test_enforce_question_length_rejects_overlong_input():
    with pytest.raises(HTTPException) as exc:
        enforce_question_length("x" * 100, max_chars=50)
    assert exc.value.status_code == 413


def test_enforce_question_length_allows_within_limit():
    enforce_question_length("apa biaya kuliah?", max_chars=50)  # no raise


def test_enforce_rate_limit_raises_429_when_over_budget():
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, clock=lambda: 0.0)
    enforce_rate_limit(limiter, "client-1")  # first request allowed
    with pytest.raises(HTTPException) as exc:
        enforce_rate_limit(limiter, "client-1")
    assert exc.value.status_code == 429
