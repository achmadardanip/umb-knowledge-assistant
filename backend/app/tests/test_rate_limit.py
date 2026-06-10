from app.core.rate_limit import SlidingWindowRateLimiter


def test_allows_up_to_limit_then_blocks():
    clock = {"t": 0.0}
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60, clock=lambda: clock["t"])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False


def test_separate_keys_have_separate_budgets():
    clock = {"t": 0.0}
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, clock=lambda: clock["t"])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip2") is True
    assert limiter.allow("ip1") is False


def test_window_slides_and_frees_budget():
    clock = {"t": 0.0}
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, clock=lambda: clock["t"])
    assert limiter.allow("ip1") is True
    assert limiter.allow("ip1") is False
    clock["t"] = 61.0
    assert limiter.allow("ip1") is True
