from __future__ import annotations

import json

from app.db.models import DiscoveredURL
from app.ingestion.umb_content import canonicalize_umb_url, classify_umb_url, clean_umb_content
from app.ingestion.umb_crawl import build_parser, import_seed_json


def test_seed_json_import_accepts_official_skips_auth_external_and_deduplicates(db, tmp_path, monkeypatch):
    seed_path = tmp_path / "seeds.json"
    seed_path.write_text(
        json.dumps(
            {
                "links": [
                    {"url": "http://www.mercubuana.ac.id/profil-universitas", "title": "Profil UMB"},
                    {"url": "https://mercubuana.ac.id/profil-universitas?utm_source=test"},
                    {"url": "https://agv-api.mercubuana.ac.id/uploads/media/laporan-k3lk.pdf"},
                    {"url": "https://publikasi.mercubuana.ac.id/index.php/fifo/login", "title": "Login"},
                    {"url": "https://example.com/not-umb"},
                    {"title": "missing"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.ingestion.umb_crawl._merge_discovery_file", lambda _urls: None)

    report = import_seed_json(
        seed_json=seed_path,
        source="test",
        confirm_authorized=True,
        require_postgres=False,
        write_report=False,
    )

    assert report["total_links_in_json"] == 6
    assert report["accepted_official_links"] == 2
    assert report["duplicate_urls"] == 1
    assert report["auth_login_urls_skipped"] == 1
    assert report["count_by_content_type"]["pdf"] == 1
    rows = db.query(DiscoveredURL).all()
    assert len(rows) == 2
    assert all(row.is_allowed for row in rows)


def test_umb_url_classification_and_canonicalization():
    assert canonicalize_umb_url("http://www.mercubuana.ac.id//lokasi-kampus/?utm_source=x") == (
        "https://mercubuana.ac.id/lokasi-kampus"
    )
    pdf = classify_umb_url("https://agv-api.mercubuana.ac.id/uploads/media/laporan-k3lk-februari-2026.pdf")
    assert pdf.content_type == "pdf"
    assert pdf.media_type == "document"
    assert pdf.page_type == "k3_report"
    assert pdf.priority >= 100
    assert classify_umb_url("https://sia.mercubuana.ac.id/gate.php/login").auth_or_system is True


def test_umb_content_cleanup_removes_floating_cta_and_repeated_chrome():
    cleaned = clean_umb_content(
        """
        Berita Akademik Universitas Mercu Buana
        Daftar Sekarang
        Daftar Sekarang
        Select Language English Indonesian French German Spanish Portuguese
        Kalender akademik tersedia untuk mahasiswa.
        Kalender akademik tersedia untuk mahasiswa.
        """
    )
    assert "Daftar Sekarang" not in cleaned
    assert "Select Language" not in cleaned
    assert cleaned.count("Kalender akademik tersedia") == 1
    assert "Berita Akademik" in cleaned


def test_full_refresh_parser_supports_required_flags():
    args = build_parser().parse_args(
        [
            "full-refresh",
            "--confirm-authorized",
            "--seed-json",
            "/tmp/seeds.json",
            "--domains",
            "mercubuana.ac.id",
            "--include-subdomains",
            "--include-sitemap",
            "--use-firecrawl-search",
            "--use-firecrawl-map",
            "--use-firecrawl-crawl",
            "--use-firecrawl-scrape",
            "--use-firecrawl-parse",
            "--use-tavily-gap-fill",
            "--include-multimodal",
            "--parse-pdf",
            "--index-images-metadata",
            "--index-video-metadata",
            "--store-supabase",
            "--update-graph",
            "--max-depth",
            "4",
            "--limit",
            "10000",
        ]
    )
    assert args.use_firecrawl_parse is True
    assert args.include_multimodal is True
    assert args.max_depth == 4
    assert args.limit == 10000
