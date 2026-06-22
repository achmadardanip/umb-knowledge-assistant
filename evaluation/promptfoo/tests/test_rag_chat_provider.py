import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag_chat_provider as p


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_success_shapes_output_and_metadata(monkeypatch):
    payload = {"answer": "Jawaban X", "not_found": False,
               "sources": [{"hostname": "pmb.mercubuana.ac.id"}],
               "retrieved_context": ["chunk a", "chunk b"]}
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: FakeResp(payload))
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert out["output"] == "Jawaban X"
    assert out["metadata"]["context"] == "chunk a\n\nchunk b"
    assert out["metadata"]["official_source"] is True
    assert out["metadata"]["not_found"] is False


def test_retrieval_mode_from_config_is_sent(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResp({"answer": "Z", "sources": [], "retrieved_context": []})

    monkeypatch.setattr(p.requests, "post", fake_post)
    p.call_api("q", {"config": {"retrieval_mode": "indexed"}}, {"vars": {"query": "q"}})
    assert captured["json"]["retrieval_mode"] == "indexed"
    assert captured["json"]["include_retrieved_context"] is True


def test_retrieval_mode_defaults_to_hybrid(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return FakeResp({"answer": "Z", "sources": [], "retrieved_context": []})

    monkeypatch.setattr(p.requests, "post", fake_post)
    p.call_api("q", {}, {"vars": {"query": "q"}})
    assert captured["json"]["retrieval_mode"] == "hybrid"


def test_non_official_source_flagged(monkeypatch):
    payload = {"answer": "Y", "sources": [{"hostname": "wikipedia.org"}],
               "retrieved_context": ["c"]}
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: FakeResp(payload))
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert out["metadata"]["official_source"] is False


def test_http_error_returns_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(p.requests, "post", boom)
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert "error" in out and "connection refused" in out["error"]
