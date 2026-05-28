import json
from pathlib import Path

import pytest

from app.discovery.discovery_pipeline import discover_subdomains_command, merge_filter_command
from app.discovery.external_tools import ToolResult, run_tool
from app.discovery.safe_wordlists import SAFE_PUBLIC_PATHS, validate_safe_wordlist
from app.discovery.subdomain_discovery import validate_hosts
from app.discovery.url_discovery import discover_urls
from app.db.models import DiscoveredURL


def test_missing_external_tools_are_handled_gracefully():
    result = run_tool("__definitely_missing_tool__", ["__definitely_missing_tool__"])
    assert result.status == "missing"


def test_ffuf_and_dirsearch_disabled_by_default():
    assert validate_safe_wordlist(SAFE_PUBLIC_PATHS)
    forbidden = {"admin", "login", "password", "config", "backup", "database", ".env", ".git", "dashboard", "private", "token", "secret", "cpanel", "phpmyadmin", "webmail"}
    assert not forbidden.intersection({path.lower() for path in SAFE_PUBLIC_PATHS})


def test_discovery_pipeline_requires_authorization_for_external_tools():
    with pytest.raises(SystemExit):
        discover_subdomains_command("mercubuana.ac.id", confirm_authorized=False)


def test_discovery_report_json_is_generated_from_merge_filter(tmp_path, monkeypatch):
    discovery_dir = tmp_path / "data" / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "urls_katana.txt").write_text("https://mercubuana.ac.id/berita\nhttps://example.com/nope\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    report = merge_filter_command("mercubuana.ac.id")
    assert report["manual_seed_subdomains_used"] is False
    assert report["urls_allowed"] == 1
    assert json.loads((discovery_dir / "discovery_report.json").read_text(encoding="utf-8"))["urls_rejected"] == 1


def test_merge_filter_keeps_subdomain_urls_and_syncs_db(tmp_path, monkeypatch, db):
    discovery_dir = tmp_path / "data" / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "urls_katana.txt").write_text(
        "\n".join(
            [
                "https://pmb.mercubuana.ac.id/pendaftaran?utm_source=test",
                "https://mercubuana.ac.id.evil.com/pendaftaran",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    report = merge_filter_command("mercubuana.ac.id")

    assert report["urls_allowed"] == 1
    assert (discovery_dir / "urls_filtered.txt").read_text(encoding="utf-8").strip() == "https://pmb.mercubuana.ac.id/pendaftaran"
    allowed = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True)).one()
    rejected = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(False)).one()
    assert allowed.hostname == "pmb.mercubuana.ac.id"
    assert allowed.path == "/pendaftaran"
    assert allowed.discovery_source == "katana"
    assert rejected.hostname == "mercubuana.ac.id.evil.com"
    assert rejected.rejection_reason == "outside_allowed_domain"


def test_no_manual_seed_subdomains_are_hardcoded():
    source = Path("app/discovery/subdomain_discovery.py").read_text(encoding="utf-8")
    assert "www.mercubuana.ac.id" not in source
    assert validate_hosts([], "mercubuana.ac.id") == ["mercubuana.ac.id"]


def test_sublist3r_result_is_primary_discovered_host_source():
    hosts = validate_hosts(["lib.mercubuana.ac.id", "example.com"], "mercubuana.ac.id")
    assert hosts == ["mercubuana.ac.id", "lib.mercubuana.ac.id"]


def test_sublist3r_runs_without_color_for_headless_windows():
    source = Path("app/discovery/subdomain_discovery.py").read_text(encoding="utf-8")
    assert '"-n"' in source


def test_url_discovery_uses_schemed_hosts_and_gau_subdomains(tmp_path, monkeypatch):
    discovery_dir = tmp_path / "data" / "discovery"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "allowed_hosts.txt").write_text("mercubuana.ac.id\npmb.mercubuana.ac.id\n", encoding="utf-8")
    calls: list[tuple[str, list[str], str | None]] = []

    def fake_run_tool(name, args, **kwargs):
        calls.append((name, args, kwargs.get("stdin")))
        return ToolResult(name=name, status="available", returncode=0)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("app.discovery.url_discovery.run_tool", fake_run_tool)

    discover_urls("mercubuana.ac.id", max_depth=5)

    host_urls = (discovery_dir / "allowed_hosts_urls.txt").read_text(encoding="utf-8").splitlines()
    assert host_urls == ["https://mercubuana.ac.id", "https://pmb.mercubuana.ac.id"]
    katana_call = next(call for call in calls if call[0] == "katana")
    assert "allowed_hosts_urls.txt" in " ".join(katana_call[1])
    gau_call = next(call for call in calls if call[0] == "gau")
    assert "--subs" in gau_call[1]
    assert "pmb.mercubuana.ac.id" in (gau_call[2] or "")
