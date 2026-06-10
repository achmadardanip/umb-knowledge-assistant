import pytest
from types import SimpleNamespace

from app.web_search.tavily_client import TavilyClient, WebSearchConfigurationError
from app.web_search.tavily_client import TavilySearchResult
from app.web_search.live_retriever import UMBLiveWebRetriever


def test_tavily_missing_key_returns_clear_error(monkeypatch):
    settings = SimpleNamespace(
        tavily_api_key=None,
        web_search_enabled=True,
        web_search_strict_domain="mercubuana.ac.id",
        web_search_timeout_seconds=10,
        web_search_top_k=5,
    )
    monkeypatch.setattr("app.web_search.tavily_client.get_settings", lambda: settings)
    with pytest.raises(WebSearchConfigurationError, match="TAVILY_API_KEY"):
        TavilyClient().search("pendaftaran", max_results=1)


def test_tavily_filters_external_and_lookalike_urls(monkeypatch):
    settings = SimpleNamespace(
        tavily_api_key="test-key",
        web_search_enabled=True,
        web_search_strict_domain="mercubuana.ac.id",
        web_search_timeout_seconds=10,
        web_search_top_k=5,
    )
    monkeypatch.setattr("app.web_search.tavily_client.get_settings", lambda: settings)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [
                    {"title": "PMB", "url": "https://pmb.mercubuana.ac.id/pendaftaran", "content": "ok", "score": 0.9},
                    {"title": "Bad", "url": "https://mercubuana.ac.id.evil.com/pendaftaran", "content": "bad", "score": 1.0},
                    {"title": "Archive", "url": "https://web.archive.org/web/202001/https://mercubuana.ac.id/", "content": "bad", "score": 1.0},
                ]
            }

    monkeypatch.setattr("app.web_search.tavily_client.requests.post", lambda *args, **kwargs: FakeResponse())
    results = TavilyClient().search("pendaftaran", max_results=3)
    assert [result.url for result in results] == ["https://pmb.mercubuana.ac.id/pendaftaran"]


def test_live_retriever_uses_firecrawl_before_direct_fetch(monkeypatch):
    calls = []
    settings = SimpleNamespace(web_search_top_k=5, rag_top_k_max=8)
    monkeypatch.setattr("app.web_search.live_retriever.get_settings", lambda: settings)
    monkeypatch.setattr(
        TavilyClient,
        "search",
        lambda _self, _query, max_results: [
            TavilySearchResult("PMB", "https://pendaftaran.mercubuana.ac.id/", "snippet only", 0.9)
        ],
    )
    monkeypatch.setattr(
        "app.web_search.live_retriever.fetch_firecrawl_contexts",
        lambda *args, **kwargs: calls.append("firecrawl")
        or [{"url": args[0], "chunk_text": "Konten resmi hasil Firecrawl", "score": 0.9}],
    )
    monkeypatch.setattr(
        "app.web_search.live_retriever.fetch_live_contexts",
        lambda *args, **kwargs: calls.append("direct") or [],
    )

    contexts = UMBLiveWebRetriever().search("cara daftar", top_k=1)

    assert calls == ["firecrawl"]
    assert contexts[0]["chunk_text"] == "Konten resmi hasil Firecrawl"
