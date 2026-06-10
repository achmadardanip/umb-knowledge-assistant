from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from app.ingestion.firecrawl_client import (
    FirecrawlAPIError,
    FirecrawlClient,
    FirecrawlConfigurationError,
    documents_from_payload,
    links_from_search_payload,
)


def test_self_hosted_base_url_adds_v2_prefix():
    client = FirecrawlClient(base_url="http://localhost:3002", timeout_seconds=10, max_retries=0)
    assert client.base_url == "http://localhost:3002/v2"


class _Response:
    def __init__(self, status_code: int, payload, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses: list[_Response | Exception]):
        self.responses = responses
        self.calls: list[dict] = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_requires_api_key_without_leaking_secret(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.firecrawl_client.get_settings",
        lambda: SimpleNamespace(
            firecrawl_api_key=None,
            firecrawl_base_url="https://api.firecrawl.dev/v2",
            firecrawl_timeout_seconds=60,
            firecrawl_max_retries=1,
            firecrawl_retry_backoff_seconds=0,
        ),
    )

    with pytest.raises(FirecrawlConfigurationError):
        FirecrawlClient()


def test_self_host_allows_missing_api_key_and_omits_auth(monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.firecrawl_client.get_settings",
        lambda: SimpleNamespace(
            firecrawl_api_key=None,
            firecrawl_base_url="http://localhost:3002",
            firecrawl_timeout_seconds=10,
            firecrawl_max_retries=0,
            firecrawl_retry_backoff_seconds=0,
        ),
    )
    session = _Session([_Response(200, {"success": True, "links": []})])
    client = FirecrawlClient(session=session)
    client.map_urls("https://mercubuana.ac.id", limit=5)
    assert "Authorization" not in session.calls[0]["headers"]


def test_map_search_and_crawl_request_bodies_match_v2_shape():
    session = _Session([_Response(200, {"success": True, "links": []}), _Response(200, {"success": True, "data": {"web": []}}), _Response(200, {"id": "job-1"})])
    client = FirecrawlClient(api_key="fc-test-token", base_url="https://api.firecrawl.dev/v2", timeout_seconds=60, session=session)

    client.map_urls("https://mercubuana.ac.id", limit=500)
    client.search_urls("Universitas Mercu Buana", limit=10, include_domains=["mercubuana.ac.id"])
    client.start_crawl(
        "https://mercubuana.ac.id",
        limit=500,
        delay_seconds=1,
        max_concurrency=2,
        zero_data_retention=True,
    )

    map_body = session.calls[0]["json"]
    assert session.calls[0]["headers"]["Authorization"] == "Bearer fc-test-token"
    assert map_body["includeSubdomains"] is True
    assert map_body["sitemap"] == "include"
    assert map_body["ignoreQueryParameters"] is True
    assert map_body["limit"] == 500

    search_body = session.calls[1]["json"]
    assert search_body["sources"] == ["web"]
    assert search_body["includeDomains"] == ["mercubuana.ac.id"]
    assert search_body["ignoreInvalidURLs"] is True

    crawl_body = session.calls[2]["json"]
    assert crawl_body["crawlEntireDomain"] is True
    assert crawl_body["allowSubdomains"] is True
    assert crawl_body["allowExternalLinks"] is False
    assert crawl_body["zeroDataRetention"] is True
    assert crawl_body["scrapeOptions"]["formats"] == ["markdown", "links", "images"]
    assert crawl_body["scrapeOptions"]["parsers"] == ["pdf"]
    assert "zeroDataRetention" not in crawl_body["scrapeOptions"]


def test_parse_uses_scrape_parser_path():
    session = _Session([_Response(200, {"success": True, "data": {"markdown": "ok"}})])
    client = FirecrawlClient(
        api_key="fc-test-token",
        base_url="http://localhost:3002",
        timeout_seconds=60,
        session=session,
    )

    client.parse("https://mercubuana.ac.id/file.pdf", zero_data_retention=False)

    assert session.calls[0]["url"] == "http://localhost:3002/v2/scrape"
    assert session.calls[0]["json"]["parsers"] == ["pdf"]


def test_retries_429_and_honors_retry_after(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.ingestion.firecrawl_client.time.sleep", lambda seconds: sleeps.append(seconds))
    session = _Session(
        [
            _Response(429, {"error": "rate limited"}, headers={"Retry-After": "0.25"}),
            _Response(200, {"success": True, "links": []}),
        ]
    )
    client = FirecrawlClient(
        api_key="fc-test-token",
        base_url="https://api.firecrawl.dev/v2",
        timeout_seconds=60,
        max_retries=1,
        retry_backoff_seconds=0.1,
        session=session,
    )

    assert client.map_urls("https://mercubuana.ac.id", limit=1)["success"] is True
    assert len(session.calls) == 2
    assert sleeps == [0.25]


def test_retries_connection_errors(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("app.ingestion.firecrawl_client.time.sleep", lambda seconds: sleeps.append(seconds))
    session = _Session(
        [
            requests.ConnectionError("connection reset"),
            _Response(200, {"status": "completed", "data": []}),
        ]
    )
    client = FirecrawlClient(
        api_key="fc-test-token",
        base_url="https://api.firecrawl.dev/v2",
        timeout_seconds=60,
        max_retries=1,
        retry_backoff_seconds=0.25,
        session=session,
    )

    assert client.get_crawl_status("job-1")["status"] == "completed"
    assert len(session.calls) == 2
    assert sleeps == [0.25]


def test_error_message_does_not_include_authorization_token():
    session = _Session([_Response(500, {"error": "server unavailable"})])
    client = FirecrawlClient(
        api_key="fc-secret-token",
        base_url="https://api.firecrawl.dev/v2",
        timeout_seconds=60,
        max_retries=0,
        session=session,
    )

    with pytest.raises(FirecrawlAPIError) as exc:
        client.search_urls("site:mercubuana.ac.id", limit=1)

    assert "fc-secret-token" not in str(exc.value)
    assert "server unavailable" in str(exc.value)


def test_parses_search_shapes_and_text_first_documents():
    assert links_from_search_payload({"data": {"web": [{"url": "https://mercubuana.ac.id/a"}]}}) == [
        {"url": "https://mercubuana.ac.id/a"}
    ]
    assert links_from_search_payload({"data": [{"url": "https://mercubuana.ac.id/b"}]}) == [
        {"url": "https://mercubuana.ac.id/b"}
    ]

    docs = documents_from_payload(
        {
            "data": {
                "markdown": "Isi PDF resmi UMB.",
                "links": ["https://mercubuana.ac.id/a"],
                "images": [{"imageUrl": "https://mercubuana.ac.id/image.jpg"}],
                "metadata": {
                    "sourceURL": "https://mercubuana.ac.id/file.pdf",
                    "title": "File PDF",
                    "statusCode": 200,
                    "contentType": "application/pdf",
                },
            }
        }
    )

    assert len(docs) == 1
    assert docs[0].url == "https://mercubuana.ac.id/file.pdf"
    assert docs[0].source_type == "pdf"
    assert docs[0].links == ["https://mercubuana.ac.id/a"]
    assert docs[0].images == ["https://mercubuana.ac.id/image.jpg"]


def test_parses_crawl_status_next_url_with_absolute_path():
    session = _Session([_Response(200, {"status": "completed", "data": []})])
    client = FirecrawlClient(api_key="fc-test-token", base_url="https://api.firecrawl.dev/v2", timeout_seconds=60, session=session)

    payload = client.get_crawl_status("https://api.firecrawl.dev/v2/crawl/job-1?skip=1")

    assert payload["status"] == "completed"
    assert session.calls[0]["url"] == "https://api.firecrawl.dev/v2/crawl/job-1?skip=1"
