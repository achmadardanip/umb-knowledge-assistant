from app.api.routes_chat import _retrieved_context_payload


def test_payload_empty_when_disabled():
    ctx = [{"chunk_text": "a"}, {"chunk_text": "b"}]
    assert _retrieved_context_payload(ctx, False) == {}


def test_payload_lists_chunks_when_enabled():
    ctx = [{"chunk_text": "a"}, {"chunk_text": "b"}, {"other": "x"}]
    out = _retrieved_context_payload(ctx, True)
    assert out["retrieved_context"] == ["a", "b", ""]
    assert out["retrieved_context_joined"] == "a\n\nb\n\n"


def test_payload_truncates_join():
    ctx = [{"chunk_text": "x" * 9000}]
    out = _retrieved_context_payload(ctx, True)
    assert len(out["retrieved_context_joined"]) == 8000
