import pytest
from types import SimpleNamespace

from app.web_search.tavily_client import TavilyClient, WebSearchConfigurationError


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
