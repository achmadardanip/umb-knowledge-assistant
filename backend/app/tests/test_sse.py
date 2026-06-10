from datetime import datetime, timezone

from app.api.routes_chat import _sse


def test_sse_serializes_datetime_without_crashing():
    # The streamed payload can carry datetime fields (source freshness); the SSE
    # encoder must not raise "Object of type datetime is not JSON serializable".
    payload = {"answer": "ok", "fetched_at": datetime(2026, 6, 7, tzinfo=timezone.utc)}
    out = _sse("final", payload)
    assert out.startswith("event: final")
    assert "2026-06-07" in out
