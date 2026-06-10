from __future__ import annotations

import pytest

from app.db.models import Chunk, DiscoveredURL, Source
from app.ingestion.embedder import BaseEmbedder
from app.ingestion.firecrawl_client import FirecrawlAPIError
from app.ingestion.firecrawl_pipeline import discover_firecrawl, run_firecrawl_index
from app.ingestion.pipeline import upsert_source_document


class _FakeEmbedder(BaseEmbedder):
    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, query):
        return [0.1, 0.2, 0.3]


@pytest.fixture(autouse=True)
def _offline_pipeline(monkeypatch):
    monkeypatch.setattr("app.ingestion.pipeline.get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr("app.ingestion.firecrawl_pipeline._write_report", lambda _report: None)
    monkeypatch.setattr("app.ingestion.firecrawl_pipeline.can_fetch", lambda _url: True)
    monkeypatch.setattr("app.ingestion.firecrawl_pipeline.time.sleep", lambda _seconds: None)


class _DiscoveryClient:
    def map_urls(self, *_args, **_kwargs):
        return {
            "links": [
                {"url": "https://mercubuana.ac.id/fakultas?utm_source=test", "title": "Fakultas"},
                {"url": "https://evil.example/nope", "title": "Outside"},
                {"url": "https://mercubuana.ac.id/login", "title": "Login"},
                {"url": "https://mercubuana.ac.id/app.js", "title": "Asset"},
            ]
        }

    def search_urls(self, *_args, **_kwargs):
        return {"data": [{"url": "https://fasilkom.mercubuana.ac.id/program-studi", "title": "Program Studi"}]}


class _IndexClient:
    def __init__(self, crawl_payloads: dict[str, list[dict]] | None = None, scrape_payload: dict | None = None):
        self.crawl_payloads = crawl_payloads or {"crawl-1": [{"status": "completed", "creditsUsed": 1, "data": []}]}
        self.scrape_payload = scrape_payload or {"data": {"markdown": "", "metadata": {"sourceURL": ""}}}
        self.scrape_calls: list[str] = []
        self.started = False

    def start_crawl(self, *_args, **_kwargs):
        self.started = True
        return {"id": "crawl-1"}

    def get_crawl_status(self, crawl_id_or_next_url):
        queue = self.crawl_payloads[str(crawl_id_or_next_url)]
        payload = queue.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload

    def scrape(self, url, **_kwargs):
        self.scrape_calls.append(url)
        return self.scrape_payload


def _words(seed: str) -> str:
    return " ".join([seed] * 35)


def test_discover_firecrawl_validates_and_persists_discovered_urls(db):
    report = discover_firecrawl(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=_DiscoveryClient(),
        limit=10,
        require_postgres=False,
    )

    accepted_urls = {row.normalized_url for row in db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True)).all()}
    rejected = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(False)).all()

    assert report["map_links_total"] == 4
    assert "https://mercubuana.ac.id/fakultas" in accepted_urls
    assert "https://fasilkom.mercubuana.ac.id/program-studi" in accepted_urls
    assert {row.rejection_reason for row in rejected} >= {
        "outside_allowed_domain",
        "sensitive_or_private_path",
        "non_knowledge_asset",
    }


def test_run_firecrawl_indexes_crawl_documents_and_metadata(db):
    client = _IndexClient(
        crawl_payloads={
            "crawl-1": [
                {
                    "status": "scraping",
                    "creditsUsed": 2,
                    "next": "next-page",
                    "data": [
                        {
                            "markdown": _words("akademik"),
                            "links": ["https://mercubuana.ac.id/kalender", "https://outside.example/nope"],
                            "images": ["https://mercubuana.ac.id/image.jpg"],
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/akademik",
                                "title": "Akademik UMB",
                                "statusCode": 200,
                            },
                        }
                    ],
                },
                {"status": "completed", "creditsUsed": 3, "data": []},
            ],
            "next-page": [
                {
                    "status": "scraping",
                    "data": [
                        {
                            "markdown": _words("pdf"),
                            "links": [],
                            "images": [],
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/panduan.pdf",
                                "title": "Panduan PDF",
                                "statusCode": 200,
                                "contentType": "application/pdf",
                            },
                        },
                        {
                            "markdown": _words("luar"),
                            "metadata": {"sourceURL": "https://outside.example/file"},
                        },
                    ],
                }
            ],
        }
    )

    report = run_firecrawl_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=client,
        limit=3,
        require_postgres=False,
    )

    assert report["crawl_job_id"] == "crawl-1"
    assert report["processed"]["indexed"] == 2
    assert report["processed"]["rejected"] == 1

    html_source = db.query(Source).filter(Source.url == "https://mercubuana.ac.id/akademik").one()
    pdf_source = db.query(Source).filter(Source.url == "https://mercubuana.ac.id/panduan.pdf").one()
    html_chunk = db.query(Chunk).filter(Chunk.source_id == html_source.id).one()
    pdf_chunk = db.query(Chunk).filter(Chunk.source_id == pdf_source.id).one()

    assert html_source.discovery_source == "firecrawl_crawl"
    assert html_chunk.extraction_method == "firecrawl"
    assert html_chunk.extraction_confidence == 0.95
    assert html_chunk.meta["links"] == ["https://mercubuana.ac.id/kalender"]
    assert html_chunk.meta["images"] == ["https://mercubuana.ac.id/image.jpg"]
    assert pdf_chunk.source_type == "pdf"


def test_run_firecrawl_skips_already_indexed_pending_urls_without_scrape(db):
    indexed_url = "https://mercubuana.ac.id/already-indexed"
    chunks = upsert_source_document(
        db,
        indexed_url,
        _words("lama"),
        "Sudah Ada",
        {},
        200,
        discovery_source="seed",
        min_words=1,
    )
    db.add(
        DiscoveredURL(
            url=indexed_url,
            normalized_url=indexed_url,
            hostname="mercubuana.ac.id",
            path="/already-indexed",
            discovery_source="firecrawl_map",
            is_allowed=True,
            indexed=False,
        )
    )
    db.commit()
    assert chunks > 0

    client = _IndexClient()
    report = run_firecrawl_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=client,
        limit=1,
        require_postgres=False,
    )

    assert report["processed"]["skipped_existing"] == 1
    assert client.scrape_calls == []
    row = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == indexed_url).one()
    assert row.indexed is True


def test_run_firecrawl_resumes_existing_job_without_starting_another(db):
    client = _IndexClient(
        crawl_payloads={
            "existing-crawl": [
                {
                    "status": "completed",
                    "data": [
                        {
                            "markdown": _words("resume"),
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/resumed",
                                "title": "Resumed",
                                "statusCode": 200,
                            },
                        }
                    ],
                }
            ]
        }
    )

    report = run_firecrawl_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=client,
        crawl_id="existing-crawl",
        limit=1,
        require_postgres=False,
    )

    assert report["crawl_job_id"] == "existing-crawl"
    assert report["processed"]["indexed"] == 1
    assert client.started is False


def test_run_firecrawl_retries_failed_pagination_on_next_poll(db):
    client = _IndexClient(
        crawl_payloads={
            "crawl-1": [
                {"status": "scraping", "next": "next-page", "data": []},
                {"status": "completed", "next": "next-page", "data": []},
            ],
            "next-page": [
                FirecrawlAPIError("connection reset"),
                {
                    "status": "scraping",
                    "data": [
                        {
                            "markdown": _words("recovered"),
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/recovered",
                                "title": "Recovered",
                                "statusCode": 200,
                            },
                        }
                    ],
                },
            ],
        }
    )

    report = run_firecrawl_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=client,
        limit=1,
        require_postgres=False,
    )

    assert report["processed"]["indexed"] == 1


def test_run_firecrawl_revisits_pagination_cursor_when_crawl_grows(db):
    client = _IndexClient(
        crawl_payloads={
            "crawl-1": [
                {"status": "scraping", "next": "next-page", "data": []},
                {"status": "completed", "next": "next-page", "data": []},
            ],
            "next-page": [
                {
                    "status": "scraping",
                    "data": [
                        {
                            "markdown": _words("first"),
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/first",
                                "title": "First",
                                "statusCode": 200,
                            },
                        }
                    ],
                },
                {
                    "status": "completed",
                    "data": [
                        {
                            "markdown": _words("second"),
                            "metadata": {
                                "sourceURL": "https://mercubuana.ac.id/second",
                                "title": "Second",
                                "statusCode": 200,
                            },
                        }
                    ],
                },
            ],
        }
    )

    report = run_firecrawl_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        client=client,
        limit=2,
        require_postgres=False,
    )

    assert report["processed"]["indexed"] == 2


def test_run_firecrawl_refuses_without_authorization_before_firecrawl_call(db):
    client = _IndexClient()

    with pytest.raises(SystemExit):
        run_firecrawl_index(
            domain="mercubuana.ac.id",
            confirm_authorized=False,
            client=client,
            limit=1,
            require_postgres=False,
        )

    assert client.started is False
