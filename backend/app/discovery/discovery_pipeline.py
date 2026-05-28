from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import get_session_local
from app.db.models import DiscoveredHost, DiscoveredURL
from app.discovery.external_tools import tool_status
from app.discovery.scope_validator import is_allowed_host, normalize_hostname, validate_url_scope
from app.discovery.subdomain_discovery import discover_subdomains
from app.discovery.url_discovery import discover_urls, discovery_dir
from app.discovery.url_normalizer import archive_to_live_candidate, normalize_url


logger = logging.getLogger(__name__)
def report_path() -> Path:
    return discovery_dir() / "discovery_report.json"


def _require_authorized(confirm_authorized: bool) -> None:
    if not confirm_authorized:
        raise SystemExit("External discovery requires --confirm-authorized.")


def _load_report(domain: str) -> dict:
    target = report_path()
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "domain": domain,
        "manual_seed_subdomains_used": False,
        "tools": {},
        "subdomains_found": 0,
        "allowed_hosts": 0,
        "urls_discovered": 0,
        "urls_allowed": 0,
        "urls_rejected": 0,
        "pages_indexed": 0,
        "index_target_sources": get_settings().index_target_sources,
        "indexed_sources_total": 0,
        "indexed_html_pages_total": 0,
        "indexed_assets_total": 0,
        "downloaded_assets_total": 0,
        "extracted_segments_total": 0,
        "crawl_failed_total": 0,
        "asset_failed_total": 0,
        "source_type_distribution": {},
    }


def _save_report(report: dict) -> None:
    target_dir = discovery_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    report_path().write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _try_session_factory():
    try:
        return get_session_local()
    except Exception as exc:
        logger.info("Discovery DB sync skipped: %s", exc)
        return None


def _sync_discovered_hosts(domain: str, hostnames: list[str], discovery_source: str = "sublist3r") -> int:
    session_factory = _try_session_factory()
    if session_factory is None:
        return 0

    synced = 0
    try:
        with session_factory() as db:
            for hostname in hostnames:
                normalized = normalize_hostname(hostname)
                if not normalized:
                    continue
                is_allowed = is_allowed_host(normalized, domain)
                existing = db.query(DiscoveredHost).filter(DiscoveredHost.hostname == normalized).first()
                if existing is None:
                    existing = DiscoveredHost(hostname=normalized)
                    db.add(existing)
                existing.root_domain = domain
                existing.discovery_source = discovery_source
                existing.is_allowed = is_allowed
                existing.rejection_reason = None if is_allowed else "outside_allowed_domain"
                existing.meta = {**(existing.meta or {}), "scope": domain}
                synced += 1
            db.commit()
    except Exception as exc:
        logger.info("Discovered host DB sync skipped: %s", exc)
        return 0
    return synced


def _sync_discovered_urls(domain: str, records: list[dict]) -> int:
    session_factory = _try_session_factory()
    if session_factory is None:
        return 0

    deduped: dict[str, dict] = {}
    for record in records:
        url = record["url"]
        existing = deduped.get(url)
        if existing is None or (record.get("is_allowed") and not existing.get("is_allowed")):
            deduped[url] = record
    records = list(deduped.values())

    synced = 0
    try:
        with session_factory() as db:
            existing_by_url: dict[str, DiscoveredURL] = {}
            urls = [record["url"] for record in records]
            for index in range(0, len(urls), 500):
                batch = urls[index : index + 500]
                existing_by_url.update({item.url: item for item in db.query(DiscoveredURL).filter(DiscoveredURL.url.in_(batch)).all()})

            for record in records:
                normalized_url = record["url"]
                parsed = urlparse(normalized_url)
                existing = existing_by_url.get(normalized_url)
                if existing is None:
                    existing = DiscoveredURL(url=normalized_url)
                    db.add(existing)
                    existing_by_url[normalized_url] = existing
                existing.normalized_url = normalized_url
                existing.hostname = normalize_hostname(parsed.hostname)
                existing.path = parsed.path or "/"
                existing.discovery_source = record.get("source")
                existing.is_allowed = bool(record.get("is_allowed"))
                existing.rejection_reason = record.get("rejection_reason")
                existing.meta = {
                    **(existing.meta or {}),
                    "scope": domain,
                    "archive_candidate": bool(record.get("archive_candidate")),
                    "original_url": record.get("original_url"),
                }
                synced += 1
            db.commit()
    except Exception as exc:
        logger.info("Discovered URL DB sync skipped: %s", exc)
        return 0
    return synced


def discover_subdomains_command(domain: str, confirm_authorized: bool) -> dict:
    _require_authorized(confirm_authorized)
    report = _load_report(domain)
    result = discover_subdomains(domain)
    allowed_hosts_path = discovery_dir() / "allowed_hosts.txt"
    allowed_hosts = []
    if allowed_hosts_path.exists():
        allowed_hosts = [line.strip() for line in allowed_hosts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    hosts_synced = _sync_discovered_hosts(domain, allowed_hosts)
    report["domain"] = domain
    report["manual_seed_subdomains_used"] = False
    report["tools"].update(result.get("tool", {}))
    report["subdomains_found"] = result["subdomains_found"]
    report["allowed_hosts"] = result["allowed_hosts"]
    report["discovered_hosts_synced"] = hosts_synced
    _save_report(report)
    return report


def discover_urls_command(domain: str, max_depth: int, confirm_authorized: bool) -> dict:
    _require_authorized(confirm_authorized)
    report = _load_report(domain)
    result = discover_urls(domain, max_depth=max_depth)
    report["tools"].update(result.get("tools", {}))
    for name in ("sublist3r", "katana", "hakrawler", "gau", "waybackurls", "ffuf", "dirsearch"):
        report["tools"].setdefault(name, tool_status(name, enabled=False if name in {"ffuf", "dirsearch"} else True))
    _save_report(report)
    return report


def merge_filter_command(domain: str | None = None) -> dict:
    settings = get_settings()
    root_domain = domain or settings.discovery_domain
    report = _load_report(root_domain)
    candidates: list[tuple[str, str, str]] = []
    files = {
        "katana": discovery_dir() / "urls_katana.txt",
        "hakrawler": discovery_dir() / "urls_hakrawler.txt",
        "gau": discovery_dir() / "urls_gau.txt",
        "waybackurls": discovery_dir() / "urls_wayback.txt",
        "ffuf": discovery_dir() / "urls_ffuf.txt",
        "dirsearch": discovery_dir() / "urls_dirsearch.txt",
    }
    existing_files = {source: path for source, path in files.items() if path.exists()}
    max_candidates = max(1, settings.discovery_max_urls)
    per_source_limit = max(1, max_candidates // max(len(existing_files), 1))
    for source, path in existing_files.items():
        source_count = 0
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if len(candidates) >= max_candidates or source_count >= per_source_limit:
                break
            value = line.strip()
            if value:
                candidates.append((source, value, archive_to_live_candidate(value)))
                source_count += 1

    allowed: list[str] = []
    rejected: list[dict] = []
    db_records: list[dict] = []
    seen: set[str] = set()
    merged_lines: list[str] = []
    for source, original_url, candidate_url in candidates:
        normalized = normalize_url(candidate_url)
        merged_lines.append(normalized)
        parsed = urlparse(normalized)
        decision = validate_url_scope(normalized, root_domain)
        if not decision.is_allowed or not is_allowed_host(parsed.hostname, root_domain):
            reason = decision.reason or "outside_allowed_domain"
            rejected.append({"url": normalized, "source": source, "reason": reason})
            db_records.append(
                {
                    "url": normalized,
                    "source": source,
                    "is_allowed": False,
                    "rejection_reason": reason,
                    "archive_candidate": original_url != candidate_url,
                    "original_url": original_url,
                }
            )
            continue
        db_records.append(
            {
                "url": normalized,
                "source": source,
                "is_allowed": True,
                "rejection_reason": None,
                "archive_candidate": original_url != candidate_url,
                "original_url": original_url,
            }
        )
        if normalized not in seen:
            seen.add(normalized)
            allowed.append(normalized)

    target_dir = discovery_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "urls_merged.txt").write_text("\n".join(sorted(set(merged_lines))) + "\n", encoding="utf-8")
    (target_dir / "urls_filtered.txt").write_text("\n".join(allowed) + "\n", encoding="utf-8")
    urls_synced = _sync_discovered_urls(root_domain, db_records)
    report.update(
        {
            "domain": root_domain,
            "manual_seed_subdomains_used": False,
            "urls_discovered": len(candidates),
            "urls_allowed": len(allowed),
            "urls_rejected": len(rejected),
            "discovered_urls_synced": urls_synced,
            "rejected_sample": rejected[:50],
        }
    )
    _save_report(report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe UMB public discovery pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    subdomains = sub.add_parser("discover-subdomains")
    subdomains.add_argument("--domain", default="mercubuana.ac.id")
    subdomains.add_argument("--confirm-authorized", action="store_true")

    urls = sub.add_parser("discover-urls")
    urls.add_argument("--domain", default="mercubuana.ac.id")
    urls.add_argument("--max-depth", type=int, default=3)
    urls.add_argument("--confirm-authorized", action="store_true")

    merge = sub.add_parser("merge-filter")
    merge.add_argument("--domain", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command == "discover-subdomains":
        report = discover_subdomains_command(args.domain, args.confirm_authorized)
    elif args.command == "discover-urls":
        report = discover_urls_command(args.domain, args.max_depth, args.confirm_authorized)
    elif args.command == "merge-filter":
        report = merge_filter_command(args.domain)
    else:
        raise SystemExit("Unknown command")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
