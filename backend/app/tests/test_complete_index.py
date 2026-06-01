from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.crawler.sitemap import fetch_sitemap_urls
from app.db.models import Chunk, DiscoveredURL, Document, Source, SourceAsset
from app.ingestion.complete_index import audit, process_url, run_complete_index
from app.ingestion.index_state import is_terminal
from app.multimodal.file_downloader import DownloadResult
from app.retrieval.hybrid_retriever import HybridRetriever


def _words(seed: str = "informasi") -> str:
    return " ".join([seed] * 30)


def _discovered(db, url: str) -> DiscoveredURL:
    row = DiscoveredURL(
        url=url,
        normalized_url=url,
        hostname=url.split("/")[2],
        path="/" + "/".join(url.split("/")[3:]),
        is_allowed=True,
        indexed=False,
        discovery_source="test",
    )
    db.add(row)
    db.commit()
    return row


def test_recursive_sitemap_parses_robots_sitemap_index_and_filters_scope(monkeypatch):
    payloads = {
        "https://mercubuana.ac.id/robots.txt": "Sitemap: https://mercubuana.ac.id/sitemap-index.xml\n",
        "https://mercubuana.ac.id/sitemap.xml": "",
        "https://mercubuana.ac.id/sitemap-index.xml": """
            <sitemapindex>
              <sitemap><loc>https://mercubuana.ac.id/post-sitemap.xml</loc></sitemap>
            </sitemapindex>
        """,
        "https://mercubuana.ac.id/post-sitemap.xml": """
            <urlset>
              <url><loc>https://mercubuana.ac.id/berita</loc></url>
              <url><loc>https://example.com/nope</loc></url>
            </urlset>
        """,
    }

    class Response:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self):
            if self.text == "":
                import requests

                raise requests.RequestException("not found")

    def fake_get(url, **_kwargs):
        return Response(payloads[url])

    monkeypatch.setattr("app.crawler.sitemap.requests.get", fake_get)

    assert fetch_sitemap_urls("https://mercubuana.ac.id") == ["https://mercubuana.ac.id/berita"]


def test_process_url_marks_http_404_terminal(db, monkeypatch):
    row = _discovered(db, "https://mercubuana.ac.id/missing")
    monkeypatch.setattr("app.ingestion.complete_index.can_fetch", lambda _url: True)
    monkeypatch.setattr(
        "app.ingestion.complete_index.fetch_page",
        lambda *_args, **_kwargs: SimpleNamespace(url=row.url, text="", status_code=404, metadata={}, title=None, links=[]),
    )

    status = process_url(db, row, domain="mercubuana.ac.id", max_attempts=2)
    db.commit()

    assert status == "terminal"
    assert is_terminal(row)
    assert row.meta["terminal_reason"] == "http_404"
    assert row.indexed is False


def test_process_url_retries_transient_failure_then_marks_terminal(db, monkeypatch):
    row = _discovered(db, "https://mercubuana.ac.id/flaky")
    monkeypatch.setattr("app.ingestion.complete_index.can_fetch", lambda _url: True)
    monkeypatch.setattr("app.ingestion.complete_index.fetch_page", lambda *_args, **_kwargs: None)

    assert process_url(db, row, domain="mercubuana.ac.id", max_attempts=2) == "retryable_failed"
    assert row.meta["crawl_status"] == "retryable_failed"
    assert not is_terminal(row)

    assert process_url(db, row, domain="mercubuana.ac.id", max_attempts=2) == "terminal"
    assert row.meta["terminal_reason"] == "transient_failure"


def test_process_url_indexes_html_source_document_and_chunk(db, monkeypatch):
    row = _discovered(db, "https://mercubuana.ac.id/berita")
    monkeypatch.setattr("app.ingestion.complete_index.can_fetch", lambda _url: True)
    monkeypatch.setattr(
        "app.ingestion.complete_index.fetch_page",
        lambda *_args, **_kwargs: SimpleNamespace(
            url=row.url,
            text=_words("pendaftaran"),
            status_code=200,
            metadata={},
            title="Berita UMB",
            links=[],
        ),
    )

    assert process_url(db, row, domain="mercubuana.ac.id", max_attempts=2) == "indexed"
    db.commit()

    source = db.query(Source).filter(Source.url == row.url).one()
    assert source.status == "indexed"
    assert db.query(Document).filter(Document.source_id == source.id).count() == 1
    assert db.query(Chunk).filter(Chunk.source_id == source.id).count() == 1
    assert row.indexed is True


def test_process_url_indexes_asset_source_asset_segment_and_chunk(db, monkeypatch, tmp_path):
    row = _discovered(db, "https://mercubuana.ac.id/file.pdf")
    local = tmp_path / "file.pdf"
    local.write_bytes(b"%PDF")
    monkeypatch.setattr("app.ingestion.complete_index.can_fetch", lambda _url: True)

    monkeypatch.setattr(
        "app.ingestion.complete_index.download_file",
        lambda _url: DownloadResult(
            url=row.url,
            status="downloaded",
            local_path=str(local),
            sha256="abc",
            file_size_bytes=4,
            mime_type="application/pdf",
            source_type="pdf",
        ),
    )
    monkeypatch.setattr(
        "app.ingestion.complete_index.extract_asset",
        lambda *_args, **_kwargs: [
            {"content": _words("pdf"), "source_type": "pdf", "page_number": 1, "extraction_method": "test", "extraction_confidence": 0.9}
        ],
    )

    assert process_url(db, row, domain="mercubuana.ac.id", max_attempts=2) == "indexed"
    db.commit()

    source = db.query(Source).filter(Source.url == row.url).one()
    assert source.status == "indexed"
    assert db.query(SourceAsset).filter(SourceAsset.source_id == source.id).count() == 1
    assert db.query(Chunk).filter(Chunk.source_id == source.id, Chunk.source_type == "pdf").count() == 1
    assert row.indexed is True


def test_run_complete_index_fixed_point_processes_until_no_pending(db, monkeypatch):
    _discovered(db, "https://mercubuana.ac.id/berita")
    _discovered(db, "https://mercubuana.ac.id/missing")
    monkeypatch.setattr("app.ingestion.complete_index._write_report", lambda _report: None)
    monkeypatch.setattr("app.ingestion.complete_index.can_fetch", lambda _url: True)

    def fake_fetch(url, **_kwargs):
        if url.endswith("/missing"):
            return SimpleNamespace(url=url, text="", status_code=404, metadata={}, title=None, links=[])
        return SimpleNamespace(url=url, text=_words("akademik"), status_code=200, metadata={}, title="Akademik", links=[])

    monkeypatch.setattr("app.ingestion.complete_index.fetch_page", fake_fetch)

    report = run_complete_index(
        domain="mercubuana.ac.id",
        confirm_authorized=True,
        offline_current_db_only=True,
        max_pages=0,
        max_passes=3,
        max_attempts=2,
        rate_limit=1000,
    )

    assert report["pending_allowed_nonterminal_total"] == 0
    assert report["indexed_sources_total"] == 1
    assert report["terminal_reasons"] == {"http_404": 1}


def test_retriever_excludes_unsafe_indexed_sources(db):
    source = Source(
        url="https://repository.mercubuana.ac.id/cgi/search",
        title="Search",
        hostname="repository.mercubuana.ac.id",
        path="/cgi/search",
        status="indexed",
    )
    db.add(source)
    db.flush()
    doc = Document(source_id=source.id, raw_text="repository search", cleaned_text="repository search")
    db.add(doc)
    db.flush()
    db.add(
        Chunk(
            document_id=doc.id,
            source_id=source.id,
            chunk_text="repository search advanced official",
            chunk_index=0,
            token_count=4,
            source_type="html",
            meta={"url": source.url, "hostname": source.hostname, "title": source.title, "source_type": "html"},
        )
    )
    db.commit()

    assert HybridRetriever(db).search("repository search", top_k=1) == []


def test_audit_reports_unsafe_indexed_sources(db):
    source = Source(url="https://mercubuana.ac.id/search", hostname="mercubuana.ac.id", path="/search", status="indexed")
    db.add(source)
    db.flush()
    db.add(Chunk(source_id=source.id, chunk_text=_words("search"), chunk_index=0, token_count=30, source_type="html"))
    db.commit()

    report = audit("mercubuana.ac.id", write_report=False)

    assert report["unsafe_indexed_sources_total"] == 1
    assert report["verification_passed"] is False
