from types import SimpleNamespace

from app.agent.umb_agent import run_umb_agent


def _context(origin: str, score: float) -> dict:
    return {
        "url": f"https://mercubuana.ac.id/{origin}",
        "hostname": "mercubuana.ac.id",
        "chunk_text": origin,
        "score": score,
        "source_type": "html",
    }


def test_agent_reranks_indexed_web_and_graph_once(db, monkeypatch):
    settings = SimpleNamespace(
        agent_max_tool_iterations=3,
        web_search_strict_domain="mercubuana.ac.id",
        reranker_enabled=True,
        reranker_candidate_k=20,
        reranker_model="BAAI/bge-reranker-v2-m3",
        graph_rag_enabled=True,
        graph_path="unused.json",
        graph_expansion_top_k=3,
        va_jit_enabled=False,
    )
    calls = {"search": [], "rerank": []}

    class _Indexed:
        def __init__(self, db, root_domain):
            pass

        def search(self, query, top_k, **kwargs):
            calls["search"].append((top_k, kwargs))
            return [_context("indexed", 0.8)]

    class _Live:
        def search(self, query, top_k):
            return [_context("web", 0.7)]

    def fake_model_rerank(query, contexts, root_domain):
        calls["rerank"].append([context["url"] for context in contexts])
        ranked = list(contexts)
        for context in ranked:
            context["reranker_used"] = True
        return ranked

    monkeypatch.setattr("app.agent.umb_agent.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.umb_agent.UMBLiveWebRetriever", _Live)
    monkeypatch.setattr("app.agent.umb_agent.model_rerank_contexts", fake_model_rerank)
    monkeypatch.setattr("app.graph.graph_store.load_graph", lambda path: object())
    monkeypatch.setattr(
        "app.graph.graph_store.expansion_contexts",
        lambda *args, **kwargs: [_context("graph", 0.6)],
    )

    result = run_umb_agent(
        db=db,
        query="program studi",
        retrieval_mode="hybrid",
        top_k=5,
        root_domain="mercubuana.ac.id",
        indexed_retriever_cls=_Indexed,
    )

    assert calls["search"] == [
        (5, {"apply_model_reranker": False, "candidate_k": 20})
    ]
    assert len(calls["rerank"]) == 1
    assert set(calls["rerank"][0]) == {
        "https://mercubuana.ac.id/indexed",
        "https://mercubuana.ac.id/web",
        "https://mercubuana.ac.id/graph",
    }
    assert len(result.contexts) == 3
