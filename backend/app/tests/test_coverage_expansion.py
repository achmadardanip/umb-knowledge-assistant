"""P2 — coverage-expansion dry-run projection + URL classification."""

from __future__ import annotations

from app.discovery.coverage_expansion_dryrun import (
    AVG_CHUNKS_PER_PAGE,
    PRIORITY_DOMAINS,
    build_report,
    classify_urls,
    project_domain,
)


def test_classify_urls_filters_archive_login_external():
    urls = [
        "https://pmb.mercubuana.ac.id/cara-pendaftaran",          # accept
        "https://baa.mercubuana.ac.id/kalender-akademik",          # accept
        "https://repository.mercubuana.ac.id/12345/thesis",        # reject: archive
        "https://sso.mercubuana.ac.id/login?service=portal",       # reject: login/stateful
        "https://example.com/phishing",                            # reject: external
    ]
    result = classify_urls(urls)
    assert len(result["accepted"]) == 2
    assert all("mercubuana.ac.id" in u for u in result["accepted"])
    assert "repository." not in " ".join(result["accepted"])
    assert sum(result["rejected"].values()) == 3
    assert "low_authority_archive" in result["rejected"]


def test_dry_run_is_pure_projection():
    report = build_report()
    assert report["dry_run"] is True
    t = report["totals"]
    # accepted pages == sum of targets; chunks == accepted * avg
    assert t["pages_accepted"] == sum(PRIORITY_DOMAINS.values())
    assert t["projected_chunks"] == t["pages_accepted"] * AVG_CHUNKS_PER_PAGE
    assert t["pages_discovered"] >= t["pages_accepted"]
    assert t["projected_postgres_growth_mb"] >= t["projected_storage_mb"]
    assert t["projected_tavily_extract_calls"] > 0
    assert len(report["per_domain"]) == len(PRIORITY_DOMAINS)


def test_project_domain_with_real_urls_classifies():
    urls = [
        "https://sia.mercubuana.ac.id/panduan-krs",
        "https://sia.mercubuana.ac.id/login?next=/dashboard",  # rejected
    ]
    p = project_domain("sia.mercubuana.ac.id", 300, discovered_urls=urls)
    assert p["mode"] == "classified"
    assert p["pages_accepted"] == 1
    assert p["pages_discovered"] == 2
    assert p["pages_rejected"] == 1
    assert p["projected_chunks"] == AVG_CHUNKS_PER_PAGE


def test_every_priority_domain_is_official_high_authority():
    report = build_report()
    for p in report["per_domain"]:
        assert p["authority"] >= 0.5  # official subdomains, not archive
