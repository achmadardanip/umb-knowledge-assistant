from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.paths import project_path
from app.crawler.crawler import fetch_page
from app.crawler.extractor import content_hash
from app.crawler.sitemap import fetch_sitemap_urls
from app.db.database import get_session_local
from app.db.models import Chunk, DiscoveredHost, DiscoveredURL, ExtractedSegment, Source, SourceAsset, utcnow
from app.discovery.discovery_pipeline import discover_subdomains_command, discover_urls_command, merge_filter_command
from app.discovery.external_tools import tool_status
from app.discovery.robots_checker import can_fetch
from app.discovery.scope_validator import is_allowed_host, normalize_hostname, validate_url_scope
from app.discovery.url_discovery import discovery_dir
from app.discovery.url_normalizer import normalize_url
from app.ingestion.chunker import chunk_segments
from app.ingestion.embedder import EmbeddingConfigurationError, get_embedder
from app.ingestion.index_state import (
    attempt_count,
    is_pending,
    is_terminal,
    mark_indexed,
    mark_retryable_failure,
    mark_terminal,
    metadata_for,
    source_has_chunks,
)
from app.ingestion.pipeline import upsert_source_document
from app.multimodal.extraction_quality import should_index
from app.multimodal.file_downloader import download_file
from app.multimodal.multimodal_pipeline import extract_asset
from app.multimodal.source_classifier import classify_source


logger = logging.getLogger(__name__)

REPORT_PATH = project_path("data", "reports", "index_completeness.json")
REQUIRED_DISCOVERY_TOOLS = ("sublist3r", "katana", "gau", "waybackurls")
OPTIONAL_DISCOVERY_TOOLS = ("hakrawler",)


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _upsert_discovered_url(db: Session, url: str, *, source: str, domain: str) -> DiscoveredURL:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    decision = validate_url_scope(normalized, domain)
    row = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalized).first()
    if row is None:
        row = DiscoveredURL(url=normalized, normalized_url=normalized)
        db.add(row)
    row.hostname = normalize_hostname(parsed.hostname)
    row.path = parsed.path or "/"
    row.discovery_source = row.discovery_source or source
    row.is_allowed = decision.is_allowed
    row.rejection_reason = None if decision.is_allowed else decision.reason
    row.meta = {**metadata_for(row), "scope": domain}
    return row


def _enabled_required_tools() -> list[str]:
    settings = get_settings()
    enabled = []
    if settings.enable_sublist3r:
        enabled.append("sublist3r")
    if settings.enable_katana:
        enabled.append("katana")
    if settings.enable_gau:
        enabled.append("gau")
    if settings.enable_waybackurls:
        enabled.append("waybackurls")
    if settings.enable_hakrawler:
        enabled.append("hakrawler")
    return enabled


def preflight_tools(*, offline_current_db_only: bool) -> dict:
    tools = {name: tool_status(name) for name in (*REQUIRED_DISCOVERY_TOOLS, *OPTIONAL_DISCOVERY_TOOLS)}
    if offline_current_db_only:
        return {"ok": True, "mode": "offline_current_db_only", "tools": tools, "missing_required": []}
    required = _enabled_required_tools()
    missing = [name for name in required if tools.get(name) != "available"]
    return {"ok": not missing, "mode": "full", "tools": tools, "missing_required": missing}


def _allowed_hosts_from_file() -> set[str]:
    path = discovery_dir() / "allowed_hosts.txt"
    if not path.exists():
        return set()
    return {normalize_hostname(line) for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()}


def allowed_hosts(db: Session, domain: str) -> list[str]:
    hosts = {normalize_hostname(domain), *_allowed_hosts_from_file()}
    hosts.update(
        hostname
        for (hostname,) in db.query(DiscoveredHost.hostname).filter(DiscoveredHost.is_allowed.is_(True)).all()
        if hostname
    )
    hosts.update(
        hostname
        for (hostname,) in db.query(DiscoveredURL.hostname).filter(DiscoveredURL.is_allowed.is_(True)).distinct().all()
        if hostname
    )
    hosts.update(hostname for (hostname,) in db.query(Source.hostname).filter(Source.status == "indexed").distinct().all() if hostname)
    cleaned = sorted(host for host in {normalize_hostname(host) for host in hosts} if is_allowed_host(host, domain))
    if normalize_hostname(domain) in cleaned:
        cleaned.remove(normalize_hostname(domain))
    return [normalize_hostname(domain), *cleaned]


def sync_sitemap_urls(db: Session, domain: str, *, timeout: int | None = None) -> dict:
    settings = get_settings()
    hosts = allowed_hosts(db, domain)
    discovered = 0
    for host in hosts:
        for url in fetch_sitemap_urls(f"https://{host}", root_domain=domain, timeout=timeout or settings.discovery_timeout_seconds):
            _upsert_discovered_url(db, url, source="sitemap", domain=domain)
            discovered += 1
        db.commit()
    return {"hosts_checked": len(hosts), "sitemap_urls_discovered": discovered}


def _terminal_reason_for_empty_page(page) -> str:
    if page.status_code in {401, 403, 404}:
        return f"http_{page.status_code}"
    if page.status_code >= 400:
        return "http_error"
    if page.metadata.get("content_type"):
        return "unsupported_content_type"
    return "empty_content"


def _mark_fetch_failure(row: DiscoveredURL, *, max_attempts: int, error: str = "empty_or_unreachable") -> str:
    if attempt_count(row) + 1 >= max_attempts:
        mark_terminal(row, reason="transient_failure", error=error)
        return "terminal"
    mark_retryable_failure(row, reason="fetch_failed", error=error)
    return "retryable_failed"


def _index_asset_url(db: Session, row: DiscoveredURL, *, max_attempts: int) -> str:
    result = download_file(row.normalized_url or row.url)
    if result.status != "downloaded" or not result.local_path:
        reason = result.reason or result.status
        if result.status == "skipped" or reason == "file_too_large":
            mark_terminal(
                row,
                reason="file_too_large" if reason == "file_too_large" else "download_failed",
                error=reason,
                final_url=result.url,
                content_type=result.mime_type,
                extra={"source_type": result.source_type},
            )
            return "terminal"
        if attempt_count(row) + 1 >= max_attempts:
            mark_terminal(row, reason="download_failed", error=reason, final_url=result.url, content_type=result.mime_type)
            return "terminal"
        mark_retryable_failure(row, reason="download_failed", error=reason, final_url=result.url, content_type=result.mime_type)
        return "retryable_failed"

    source_type = result.source_type or classify_source(result.url, result.mime_type, result.local_path).source_type
    segments = [
        {**segment, "url": result.url}
        for segment in extract_asset(result.local_path, source_type, result.url)
        if should_index(segment.get("content", ""), get_settings().multimodal_min_extraction_chars, segment.get("extraction_confidence"))
    ]
    if not segments:
        mark_terminal(
            row,
            reason="extraction_failed",
            final_url=result.url,
            content_type=result.mime_type,
            extra={"source_type": source_type, "file_size_bytes": result.file_size_bytes},
        )
        return "terminal"

    parsed = urlparse(result.url)
    hostname = normalize_hostname(parsed.hostname)
    path = parsed.path or "/"
    title = Path(path).name or result.url
    combined_text = "\n\n".join(segment.get("content", "") for segment in segments)
    source = db.query(Source).filter(Source.url == result.url).first()
    if source is None:
        source = Source(url=result.url)
        db.add(source)
        db.flush()
    source.title = title
    source.hostname = hostname
    source.path = path
    source.content_hash = content_hash(combined_text)
    source.status = "indexed"
    source.discovery_source = source.discovery_source or row.discovery_source or "complete_index"
    source.http_status = 200

    asset = db.query(SourceAsset).filter(SourceAsset.normalized_url == result.url).first()
    if asset is None:
        asset = SourceAsset(url=result.url, normalized_url=result.url)
        db.add(asset)
        db.flush()
    db.query(Chunk).filter(Chunk.asset_id == asset.id).delete(synchronize_session=False)
    db.query(ExtractedSegment).filter(ExtractedSegment.asset_id == asset.id).delete(synchronize_session=False)

    asset.source_id = source.id
    asset.discovered_url_id = row.id
    asset.hostname = hostname
    asset.path = path
    asset.source_type = source_type
    asset.mime_type = result.mime_type
    asset.file_extension = Path(path).suffix.lower() or None
    asset.file_size_bytes = result.file_size_bytes
    asset.sha256 = result.sha256
    asset.local_path = result.local_path
    asset.download_status = "downloaded"
    asset.extraction_status = "indexed"
    asset.downloaded_at = utcnow()
    asset.extracted_at = utcnow()
    asset.meta = {**(asset.meta or {}), "source_url": result.url, "title": title}

    try:
        embedder = get_embedder()
    except EmbeddingConfigurationError:
        embedder = None

    indexed_chunks = 0
    for segment_index, segment in enumerate(segments):
        extracted = ExtractedSegment(
            asset_id=asset.id,
            source_id=source.id,
            segment_type=segment.get("source_type") or source_type,
            content=segment.get("content", ""),
            page_number=segment.get("page_number"),
            slide_number=segment.get("slide_number"),
            sheet_name=segment.get("sheet_name"),
            row_range=segment.get("row_range"),
            timestamp_start=segment.get("timestamp_start"),
            timestamp_end=segment.get("timestamp_end"),
            extraction_confidence=segment.get("extraction_confidence"),
            meta={
                "url": result.url,
                "hostname": hostname,
                "path": path,
                "title": title,
                "source_type": segment.get("source_type") or source_type,
                "extraction_method": segment.get("extraction_method"),
                "segment_index": segment_index,
            },
        )
        db.add(extracted)
        db.flush()
        metadata = {
            **(extracted.meta or {}),
            "page_number": extracted.page_number,
            "slide_number": extracted.slide_number,
            "sheet_name": extracted.sheet_name,
            "row_range": extracted.row_range,
            "timestamp_start": extracted.timestamp_start,
            "timestamp_end": extracted.timestamp_end,
            "extraction_confidence": extracted.extraction_confidence,
        }
        chunks = chunk_segments([{**metadata, "content": extracted.content}], chunk_size=get_settings().chunk_size, overlap=get_settings().chunk_overlap)
        embeddings = [None] * len(chunks)
        if embedder and chunks:
            try:
                embeddings = embedder.embed_texts([chunk.chunk_text for chunk in chunks])
            except Exception as exc:
                logger.warning("Embedding failed for %s; indexing keyword-only asset chunks: %s", result.url, exc)
        for chunk, embedding in zip(chunks, embeddings):
            chunk_values = {
                "source_id": source.id,
                "asset_id": asset.id,
                "segment_id": extracted.id,
                "chunk_text": chunk.chunk_text,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "meta": chunk.metadata,
                "source_type": chunk.source_type,
                "page_number": chunk.page_number,
                "slide_number": chunk.slide_number,
                "sheet_name": chunk.sheet_name,
                "row_range": chunk.row_range,
                "timestamp_start": chunk.timestamp_start,
                "timestamp_end": chunk.timestamp_end,
                "extraction_method": chunk.extraction_method,
                "extraction_confidence": chunk.extraction_confidence,
            }
            if embedding is not None:
                chunk_values["embedding"] = embedding
            db.add(Chunk(**chunk_values))
            indexed_chunks += 1

    if indexed_chunks <= 0:
        mark_terminal(row, reason="extraction_failed", final_url=result.url, content_type=result.mime_type, extra={"source_type": source_type})
        return "terminal"
    mark_indexed(row, http_status=200, final_url=result.url, content_type=result.mime_type)
    return "indexed"


def process_url(db: Session, row: DiscoveredURL, *, domain: str, max_attempts: int) -> str:
    normalized = normalize_url(row.normalized_url or row.url)
    decision = validate_url_scope(normalized, domain)
    if not decision.is_allowed:
        row.is_allowed = False
        row.rejection_reason = decision.reason
        mark_terminal(row, reason="unsafe_scope", error=decision.reason)
        return "terminal"
    if is_terminal(row):
        return "terminal"
    if row.indexed and source_has_chunks(db, normalized):
        return "indexed"
    row.normalized_url = normalized
    row.url = row.url or normalized
    row.indexed = False

    if not can_fetch(normalized):
        mark_terminal(row, reason="robots_disallowed")
        return "terminal"

    classification = classify_source(normalized)
    if classification.source_type not in {"html", "unknown"}:
        return _index_asset_url(db, row, max_attempts=max_attempts)

    page = fetch_page(normalized, timeout=get_settings().crawler_timeout_seconds)
    if not page:
        return _mark_fetch_failure(row, max_attempts=max_attempts)
    if not page.text:
        mark_terminal(
            row,
            reason=_terminal_reason_for_empty_page(page),
            http_status=page.status_code,
            final_url=page.url,
            content_type=page.metadata.get("content_type"),
        )
        return "terminal"

    chunks = upsert_source_document(db, page.url, page.text, page.title, page.metadata, page.status_code, discovery_source=row.discovery_source or "complete_index")
    if chunks > 0:
        mark_indexed(row, http_status=page.status_code, final_url=page.url, content_type="text/html")
        return "indexed"
    mark_terminal(row, reason="empty_content", http_status=page.status_code, final_url=page.url, content_type="text/html")
    return "terminal"


def pending_rows(db: Session, *, limit: int | None = None) -> list[DiscoveredURL]:
    query = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True), DiscoveredURL.indexed.is_(False)).order_by(DiscoveredURL.discovered_at.asc())
    if limit:
        query = query.limit(limit)
    return [row for row in query.all() if is_pending(row)]


def exclude_unsafe_indexed_sources(db: Session, domain: str) -> int:
    excluded = 0
    chunked_source_ids = {source_id for (source_id,) in db.query(Chunk.source_id).filter(Chunk.source_id.isnot(None)).distinct().all()}
    rows = db.query(Source).filter(Source.status == "indexed").all()
    for source in rows:
        scope_decision = validate_url_scope(source.url, domain)
        if scope_decision.is_allowed and source.id in chunked_source_ids:
            continue
        source.status = "excluded"
        discovered = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalize_url(source.url)).first()
        if discovered:
            reason = "empty_content" if scope_decision.is_allowed else "unsafe_scope"
            mark_terminal(discovered, reason=reason, final_url=source.url)
        excluded += 1
    db.commit()
    return excluded


def audit(domain: str = "mercubuana.ac.id", *, write_report: bool = True) -> dict:
    session_factory = get_session_local()
    with session_factory() as db:
        terminal_rows = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True), DiscoveredURL.indexed.is_(False)).all()
        terminal_reason_counts = Counter((metadata_for(row).get("terminal_reason") or "unknown") for row in terminal_rows if is_terminal(row))
        pending = [row for row in terminal_rows if is_pending(row)]
        chunked_source_ids = {source_id for (source_id,) in db.query(Chunk.source_id).filter(Chunk.source_id.isnot(None)).distinct().all()}
        indexed_sources = db.query(Source).filter(Source.status == "indexed").all()
        unsafe_sources = [source.url for source in indexed_sources if not validate_url_scope(source.url, domain).is_allowed]
        chunkless_sources = [source.url for source in indexed_sources if validate_url_scope(source.url, domain).is_allowed and source.id not in chunked_source_ids]
        report = {
            "domain": domain,
            "generated_at": utcnow().isoformat(),
            "indexed_sources_total": db.query(Source).filter(Source.status == "indexed").count(),
            "chunks_total": db.query(Chunk).count(),
            "allowed_discovered_urls_total": db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True)).count(),
            "rejected_discovered_urls_total": db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(False)).count(),
            "pending_allowed_nonterminal_total": len(pending),
            "terminal_allowed_total": sum(terminal_reason_counts.values()),
            "terminal_reasons": dict(sorted(terminal_reason_counts.items())),
            "unsafe_indexed_sources_total": len(unsafe_sources),
            "unsafe_indexed_sources_sample": unsafe_sources[:50],
            "indexed_without_chunks_total": len(chunkless_sources),
            "indexed_without_chunks_sample": chunkless_sources[:50],
            "invalid_indexed_sources_total": len(unsafe_sources) + len(chunkless_sources),
            "indexed_by_host": {
                host or "unknown": int(count)
                for host, count in db.query(Source.hostname, func.count(Source.id)).filter(Source.status == "indexed").group_by(Source.hostname).all()
            },
            "pending_by_host": Counter(row.hostname or "unknown" for row in pending),
            "source_type_distribution": {
                source_type or "unknown": int(count)
                for source_type, count in db.query(Chunk.source_type, func.count(Chunk.id)).group_by(Chunk.source_type).all()
            },
        }
    report["pending_by_host"] = dict(report["pending_by_host"])
    report["verification_passed"] = report["pending_allowed_nonterminal_total"] == 0 and report["invalid_indexed_sources_total"] == 0
    if write_report:
        _write_report(report)
    return report


def run_complete_index(
    *,
    domain: str,
    confirm_authorized: bool,
    offline_current_db_only: bool = False,
    max_pages: int | None = None,
    max_passes: int = 5,
    max_attempts: int = 2,
    rate_limit: float | None = None,
) -> dict:
    if not confirm_authorized:
        raise SystemExit("Complete indexing a real domain requires --confirm-authorized.")
    preflight = preflight_tools(offline_current_db_only=offline_current_db_only)
    if not preflight["ok"]:
        missing = ", ".join(preflight["missing_required"])
        raise SystemExit(f"Missing required discovery tools for full indexing: {missing}. Use --offline-current-db-only for backlog-only runs.")

    settings = get_settings()
    max_pages = settings.crawler_max_pages if max_pages is None else max_pages
    delay = 1.0 / max(rate_limit if rate_limit is not None else settings.crawler_rate_limit, 0.1)
    session_factory = get_session_local()

    discovery_report: dict = {"mode": preflight["mode"], "tools": preflight["tools"]}
    if not offline_current_db_only:
        discovery_report["subdomains"] = discover_subdomains_command(domain, confirm_authorized=True)
        discovery_report["urls"] = discover_urls_command(domain, max_depth=settings.discovery_max_depth, confirm_authorized=True)
        discovery_report["merge"] = merge_filter_command(domain)

    with session_factory() as db:
        if not offline_current_db_only:
            discovery_report["sitemaps"] = sync_sitemap_urls(db, domain)
        excluded_sources = exclude_unsafe_indexed_sources(db, domain)

        processed = Counter()
        processed_total = 0
        for _pass in range(max(1, max_passes)):
            remaining_budget = None if max_pages <= 0 else max_pages - processed_total
            if remaining_budget is not None and remaining_budget <= 0:
                break
            rows = pending_rows(db, limit=remaining_budget)
            if not rows:
                break
            for row in rows:
                status = process_url(db, row, domain=domain, max_attempts=max_attempts)
                processed[status] += 1
                processed_total += 1
                db.commit()
                time.sleep(delay)
                if max_pages > 0 and processed_total >= max_pages:
                    break
        excluded_sources += exclude_unsafe_indexed_sources(db, domain)

    report = audit(domain, write_report=False)
    report.update(
        {
            "run": {
                "processed_total": processed_total,
                "processed": dict(processed),
                "excluded_sources": excluded_sources,
                "max_pages": max_pages,
                "max_passes": max_passes,
                "max_attempts": max_attempts,
            },
            "discovery": discovery_report,
        }
    )
    _write_report(report)
    return report


def verify(domain: str = "mercubuana.ac.id") -> dict:
    return audit(domain)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete public UMB indexing workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--domain", default="mercubuana.ac.id")
    audit_parser.add_argument("--no-write-report", action="store_true")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--domain", default="mercubuana.ac.id")
    run_parser.add_argument("--confirm-authorized", action="store_true")
    run_parser.add_argument("--offline-current-db-only", action="store_true")
    run_parser.add_argument("--max-pages", type=int, default=None)
    run_parser.add_argument("--max-passes", type=int, default=5)
    run_parser.add_argument("--max-attempts", type=int, default=2)
    run_parser.add_argument("--rate-limit", type=float, default=None)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--domain", default="mercubuana.ac.id")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command == "audit":
        report = audit(args.domain, write_report=not args.no_write_report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "run":
        report = run_complete_index(
            domain=args.domain,
            confirm_authorized=args.confirm_authorized,
            offline_current_db_only=args.offline_current_db_only,
            max_pages=args.max_pages,
            max_passes=args.max_passes,
            max_attempts=args.max_attempts,
            rate_limit=args.rate_limit,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "verify":
        report = verify(args.domain)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["verification_passed"] else 1
    raise SystemExit("Unknown command")


if __name__ == "__main__":
    sys.exit(main())
