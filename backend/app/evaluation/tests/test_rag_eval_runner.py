import pytest
from app.evaluation import rag_eval_runner as r


def test_start_run_rejects_when_active(monkeypatch):
    monkeypatch.setattr(r, "_active_run_id", "existing")
    with pytest.raises(RuntimeError, match="already in progress"):
        r.start_run()


def test_start_run_rejects_empty_slice(monkeypatch):
    monkeypatch.setattr(r, "_active_run_id", None)
    monkeypatch.setattr(r, "_load_slice", lambda: [])
    with pytest.raises(RuntimeError, match="empty"):
        r.start_run()


def test_subscribe_unsubscribe_roundtrip():
    q = r.subscribe("run-1")
    r._publish("run-1", {"event": "ping", "data": {}})
    assert q.get_nowait() == {"event": "ping", "data": {}}
    r.unsubscribe("run-1", q)
    r._publish("run-1", {"event": "ping", "data": {}})
    assert q.empty()
