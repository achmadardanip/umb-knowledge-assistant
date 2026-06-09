import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.retrieval import reranker as module


def _settings(**overrides):
    values = {
        "reranker_model": "test/bge",
        "reranker_batch_size": 4,
        "reranker_max_length": 512,
        "reranker_device": "cpu",
        "reranker_provider": "local_bge",
        "reranker_candidate_k": 20,
        "reranker_model_weight": 0.8,
        "tahf_authority_weight": 1.0,
        "tahf_freshness_weight": 0.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _context(url: str, score: float) -> dict:
    return {
        "url": url,
        "hostname": "mercubuana.ac.id",
        "title": "Title",
        "chunk_text": f"Document at {url}",
        "score": score,
        "retrieval_score": score,
        "source_type": "html",
        "freshness": 1.0,
    }


def test_local_bge_cache_and_batch_configuration(monkeypatch):
    module._clear_reranker_cache()
    calls = []

    class _Encoder:
        def predict(self, pairs, **kwargs):
            calls.append((pairs, kwargs))
            return [0.0, 2.0]

    builds = []
    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        module,
        "_build_cross_encoder",
        lambda model, device, max_length: builds.append((model, device, max_length)) or _Encoder(),
    )

    first = module.LocalBGEReranker()
    second = module.LocalBGEReranker()
    scores = first.score("query", ["one", "two"])
    second.score("query", ["one", "two"])

    assert builds == [("test/bge", "cpu", 512)]
    assert calls[0][1]["batch_size"] == 4
    assert scores == pytest.approx([0.5, 0.880797], abs=1e-6)


def test_local_bge_serializes_concurrent_inference(monkeypatch):
    module._clear_reranker_cache()
    state = {"active": 0, "max_active": 0}
    state_lock = threading.Lock()

    class _Encoder:
        def predict(self, pairs, **kwargs):
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            time.sleep(0.02)
            with state_lock:
                state["active"] -= 1
            return [0.0 for _ in pairs]

    monkeypatch.setattr(module, "get_settings", lambda: _settings())
    monkeypatch.setattr(module, "_build_cross_encoder", lambda *args, **kwargs: _Encoder())
    reranker = module.LocalBGEReranker()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: reranker.score("query", ["document"]), range(2)))

    assert state["max_active"] == 1


def test_model_reranker_blends_scores_and_records_diagnostics(monkeypatch):
    monkeypatch.setattr(module, "get_settings", lambda: _settings())

    class _Reranker:
        model = "test/bge"

        def score(self, query, documents):
            assert query == "program studi fasilkom"
            assert len(documents) == 2
            return [0.1, 0.9]

    contexts = [_context("https://mercubuana.ac.id/noisy", 10.0), _context("https://mercubuana.ac.id/fik", 1.0)]
    ranked = module.model_rerank_contexts(
        "program studi fasilkom",
        contexts,
        reranker=_Reranker(),
    )

    assert ranked[0]["url"].endswith("/fik")
    assert ranked[0]["reranker_score"] == 0.9
    assert ranked[0]["reranker_model"] == "test/bge"
    assert ranked[0]["reranker_used"] is True
    assert ranked[0]["retrieval_score"] == 1.0


def test_model_reranker_preserves_baseline_on_failure(monkeypatch):
    monkeypatch.setattr(module, "get_settings", lambda: _settings())

    class _BrokenReranker:
        model = "broken"

        def score(self, query, documents):
            raise RuntimeError("inference failed")

    contexts = [_context("https://mercubuana.ac.id/first", 2.0), _context("https://mercubuana.ac.id/second", 1.0)]
    ranked = module.model_rerank_contexts("query", contexts, reranker=_BrokenReranker())

    assert [context["url"] for context in ranked] == [
        "https://mercubuana.ac.id/first",
        "https://mercubuana.ac.id/second",
    ]
    assert all("reranker_score" not in context for context in ranked)


def test_model_reranker_preserves_baseline_on_invalid_score_count(monkeypatch):
    monkeypatch.setattr(module, "get_settings", lambda: _settings())

    class _InvalidReranker:
        model = "invalid"

        def score(self, query, documents):
            return [0.5]

    contexts = [_context("https://mercubuana.ac.id/first", 2.0), _context("https://mercubuana.ac.id/second", 1.0)]
    ranked = module.model_rerank_contexts("query", contexts, reranker=_InvalidReranker())

    assert [context["url"] for context in ranked] == [
        "https://mercubuana.ac.id/first",
        "https://mercubuana.ac.id/second",
    ]
    assert all("reranker_score" not in context for context in ranked)
