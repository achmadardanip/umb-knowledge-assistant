from fastapi.testclient import TestClient

from app.core.rate_limit import SlidingWindowRateLimiter
from app.main import app

client = TestClient(app)


def test_chat_rejects_overlong_question():
    response = client.post("/chat", json={"anonymous_session_id": "anon-len", "question": "x" * 5000})
    assert response.status_code == 413


def test_chat_is_rate_limited_per_client(monkeypatch):
    limiter = SlidingWindowRateLimiter(max_requests=1, window_seconds=60, clock=lambda: 0.0)
    monkeypatch.setattr("app.api.chat_guards.get_chat_rate_limiter", lambda: limiter)
    # Stub the heavy pipeline so the first (allowed) request returns without LLM/network.
    monkeypatch.setattr(
        "app.api.routes_chat.process_chat",
        lambda payload, db: {"answer": "ok", "sources": [], "not_found": False},
    )
    body = {"anonymous_session_id": "anon-rl", "question": "halo"}
    assert client.post("/chat", json=body).status_code == 200
    assert client.post("/chat", json=body).status_code == 429
