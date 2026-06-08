import time

from app.chat.prepare_store import PreparedGeneration, PrepareStore


def _prep(**over) -> PreparedGeneration:
    base = dict(
        session_id="s1", raw_question="q", contexts=[{"url": "u"}], language="id",
        intent="general", retrieval_mode="indexed", memory_used=False, top_k=5,
        indexed_context_count=1, web_context_count=0, agent_tool_calls=0, visible_steps=[],
    )
    base.update(over)
    return PreparedGeneration(**base)


def test_put_get_roundtrip_preserves_contexts():
    store = PrepareStore(ttl_seconds=100)
    key = store.put(_prep())
    got = store.get(key)
    assert got is not None
    assert got.session_id == "s1"
    assert got.contexts == [{"url": "u"}]


def test_get_missing_returns_none():
    assert PrepareStore().get("nope") is None


def test_pop_consumes_entry():
    store = PrepareStore()
    key = store.put(_prep())
    assert store.pop(key) is not None
    assert store.get(key) is None


def test_expired_entries_are_pruned():
    store = PrepareStore(ttl_seconds=0.0)
    key = store.put(_prep())
    time.sleep(0.01)
    assert store.get(key) is None
