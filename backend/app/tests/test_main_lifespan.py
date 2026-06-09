from types import SimpleNamespace

from app import main


def test_prewarm_skips_when_dense_local_embeddings_are_not_active(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(embedding_provider="gemini", dense_retrieval_enabled=True),
    )
    monkeypatch.setattr(
        main.threading,
        "Thread",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("thread should not start")),
    )

    main._prewarm_local_embedder()


def test_prewarm_starts_daemon_thread_and_embeds_query(monkeypatch):
    calls = []

    class _Embedder:
        def embed_query(self, query):
            calls.append(query)

    class _Thread:
        def __init__(self, *, target, daemon, name=None):
            calls.append(("thread", daemon, name))
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(embedding_provider="local_e5", dense_retrieval_enabled=True),
    )
    monkeypatch.setattr(main, "get_embedder", lambda: _Embedder())
    monkeypatch.setattr(main.threading, "Thread", _Thread)

    main._prewarm_local_embedder()

    assert calls == [("thread", True, "local-e5-prewarm"), "warmup"]


def test_reranker_prewarm_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(reranker_enabled=False, reranker_prewarm_enabled=True),
    )
    monkeypatch.setattr(
        main.threading,
        "Thread",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("thread should not start")),
    )

    main._prewarm_local_reranker()


def test_reranker_prewarm_is_non_blocking(monkeypatch):
    calls = []

    class _Reranker:
        def score(self, query, documents):
            calls.append((query, documents))

    class _Thread:
        def __init__(self, *, target, daemon, name=None):
            calls.append(("thread", daemon, name))
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(reranker_enabled=True, reranker_prewarm_enabled=True),
    )
    monkeypatch.setattr(main, "get_reranker", lambda: _Reranker())
    monkeypatch.setattr(main.threading, "Thread", _Thread)

    main._prewarm_local_reranker()

    assert calls == [
        ("thread", True, "local-bge-reranker-prewarm"),
        ("warmup", ["warmup"]),
    ]
