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
from app.db.database import get_session_local
from app.db.models import Chunk, DiscoveredURL, Source, utcnow
from app.discovery.robots_checker import can_fetch
from app.discovery.scope_validator import normalize_hostname, validate_url_scope
from app.discovery.url_normalizer import normalize_url
from app.ingestion.complete_index import audit as complete_audit
from app.ingestion.firecrawl_client import (
    FirecrawlAPIError,
    FirecrawlClient,
    FirecrawlDocument,
    documents_from_payload,
    links_from_map_payload,
    links_from_search_payload,
)
from app.ingestion.index_state import is_pending, mark_indexed, mark_retryable_failure, mark_terminal, metadata_for, source_has_chunks
from app.ingestion.pipeline import upsert_source_document


logger = logging.getLogger(__name__)

REPORT_PATH = project_path("data", "reports", "firecrawl_index.json")

SEARCH_DISCOVERY_QUERIES = (
    "Universitas Mercu Buana",
    "Universitas Mercu Buana program studi",
    "Universitas Mercu Buana fakultas",
    "Universitas Mercu Buana pendaftaran",
    "Universitas Mercu Buana akademik",
)


def _write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def _ensure_postgres(db: Session) -> None:
    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect_name != "postgresql":
        raise SystemExit(
            "Firecrawl indexing must target Supabase/PostgreSQL. Configure SUPABASE_POOLER_DATABASE_URL or DATABASE_URL "
            "and keep LOCAL_SQLITE_FALLBACK_ENABLED=false."
        )


def _upsert_discovered_url(
    db: Session,
    url: str,
    *,
    discovery_source: str,
    domain: str,
    title: str | None = None,
    description: str | None = None,
    extra: dict | None = None,
) -> DiscoveredURL:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    decision = validate_url_scope(normalized, domain)
    row = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalized).first()
    if row is None:
        row = DiscoveredURL(url=normalized, normalized_url=normalized)
        db.add(row)
        db.flush()
    row.hostname = normalize_hostname(parsed.hostname)
    row.path = parsed.path or "/"
    row.discovery_source = discovery_source if not row.discovery_source else row.discovery_source
    row.is_allowed = decision.is_allowed
    row.rejection_reason = None if decision.is_allowed else decision.reason
    row.meta = {
        **metadata_for(row),
        "firecrawl": True,
        "firecrawl_discovery_source": discovery_source,
        "title": title,
        "description": description,
        **(extra or {}),
    }
    return row


def _source_metadata(document: FirecrawlDocument, domain: str, discovery_source: str) -> dict:
    return {
        **(document.metadata or {}),
        "source_type": document.source_type,
        "links": _valid_related_urls(document.links, domain),
        "images": _valid_related_urls(document.images, domain),
        "ingested_via": "firecrawl",
        "firecrawl_discovery_source": discovery_source,
    }


def _valid_related_urls(urls: list[str], domain: str) -> list[str]:
    valid: list[str] = []
    seen: set[str] = set()
    for raw_url in urls:
        normalized = normalize_url(raw_url)
        if not normalized or not validate_url_scope(normalized, domain).is_allowed:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        valid.append(normalized)
    return valid


def _save_firecrawl_document(
    db: Session,
    document: FirecrawlDocument,
    *,
    domain: str,
    discovery_source: str,
    skip_existing: bool = True,
) -> str:
    normalized = normalize_url(document.url)
    decision = validate_url_scope(normalized, domain)
    row = _upsert_discovered_url(
        db,
        normalized,
        discovery_source=discovery_source,
        domain=domain,
        title=document.title,
        extra={"source_type": document.source_type},
    )
    if not decision.is_allowed:
        mark_terminal(row, reason="unsafe_scope", error=decision.reason, final_url=normalized)
        return "rejected"
    if skip_existing and source_has_chunks(db, normalized):
        mark_indexed(row, http_status=document.status_code, final_url=normalized, content_type=document.source_type)
        return "skipped_existing"
    if not document.markdown.strip():
        mark_terminal(row, reason="empty_content", http_status=document.status_code, final_url=normalized, content_type=document.source_type)
        return "empty"

    chunks = upsert_source_document(
        db,
        normalized,
        document.markdown,
        document.title,
        _source_metadata(document, domain, discovery_source),
        document.status_code,
        discovery_source=discovery_source,
        min_words=1,
        source_type=document.source_type,
        extraction_method="firecrawl",
        extraction_confidence=0.95,
    )
    if chunks <= 0:
        mark_terminal(row, reason="empty_content", http_status=document.status_code, final_url=normalized, content_type=document.source_type)
        return "empty"
    mark_indexed(row, http_status=document.status_code, final_url=normalized, content_type=document.source_type)
    for related_url in _valid_related_urls(document.links, domain):
        _upsert_discovered_url(db, related_url, discovery_source="firecrawl_crawl", domain=domain)
    return "indexed"


def discover_firecrawl(
    *,
    domain: str,
    confirm_authorized: bool,
    client: FirecrawlClient | None = None,
    limit: int | None = None,
    require_postgres: bool = True,
) -> dict:
    if not confirm_authorized:
        raise SystemExit("Firecrawl discovery requires --confirm-authorized for the real UMB domain.")
    settings = get_settings()
    limit = max(1, limit or settings.firecrawl_default_limit)
    client = client or FirecrawlClient()
    session_factory = get_session_local()
    report = {
        "domain": domain,
        "generated_at": utcnow().isoformat(),
        "mode": "discover",
        "limit": limit,
        "map_links_total": 0,
        "search_links_total": 0,
        "accepted": 0,
        "rejected": 0,
    }
    with session_factory() as db:
        if require_postgres:
            _ensure_postgres(db)
        map_payload = client.map_urls(f"https://{domain}", limit=limit, include_subdomains=True)
        map_links = links_from_map_payload(map_payload)
        report["map_links_total"] = len(map_links)
        for link in map_links:
            row = _upsert_discovered_url(
                db,
                str(link.get("url") or ""),
                discovery_source="firecrawl_map",
                domain=domain,
                title=link.get("title"),
                description=link.get("description"),
            )
            report["accepted" if row.is_allowed else "rejected"] += 1

        per_query_limit = max(1, min(20, limit // max(len(SEARCH_DISCOVERY_QUERIES), 1)))
        for query in SEARCH_DISCOVERY_QUERIES:
            payload = client.search_urls(query, limit=per_query_limit, include_domains=[domain])
            links = links_from_search_payload(payload)
            report["search_links_total"] += len(links)
            for link in links:
                row = _upsert_discovered_url(
                    db,
                    str(link.get("url") or ""),
                    discovery_source="firecrawl_search",
                    domain=domain,
                    title=link.get("title"),
                    description=link.get("description"),
                    extra={"search_query": query},
                )
                report["accepted" if row.is_allowed else "rejected"] += 1
        db.commit()
        report.update(_db_counts(db, domain))
    _write_report(report)
    return report


def run_firecrawl_index(
    *,
    domain: str,
    confirm_authorized: bool,
    client: FirecrawlClient | None = None,
    crawl_id: str | None = None,
    limit: int | None = None,
    skip_existing: bool = True,
    poll_interval_seconds: float | None = None,
    max_wait_seconds: int | None = None,
    require_postgres: bool = True,
) -> dict:
    if not confirm_authorized:
        raise SystemExit("Firecrawl indexing requires --confirm-authorized for the real UMB domain.")
    settings = get_settings()
    client = client or FirecrawlClient()
    limit = max(1, limit or settings.firecrawl_default_limit)
    poll_interval_seconds = poll_interval_seconds if poll_interval_seconds is not None else settings.firecrawl_poll_interval_seconds
    max_wait_seconds = max_wait_seconds if max_wait_seconds is not None else settings.firecrawl_max_wait_seconds

    session_factory = get_session_local()
    report = {
        "domain": domain,
        "generated_at": utcnow().isoformat(),
        "mode": "run",
        "limit": limit,
        "skip_existing": skip_existing,
        "crawl_job_id": None,
        "crawl_status": None,
        "credits_used": None,
        "processed": {},
    }
    processed = Counter()
    documents_seen: set[str] = set()

    with session_factory() as db:
        if require_postgres:
            _ensure_postgres(db)

    active_crawl_id = str(crawl_id or "").strip()
    if not active_crawl_id:
        crawl_payload = client.start_crawl(
            f"https://{domain}",
            limit=limit,
            delay_seconds=settings.firecrawl_delay_seconds,
            max_concurrency=settings.firecrawl_max_concurrency,
            zero_data_retention=settings.firecrawl_zero_data_retention,
        )
        active_crawl_id = str(crawl_payload.get("id") or crawl_payload.get("jobId") or "").strip()
        if not active_crawl_id:
            raise FirecrawlAPIError("Firecrawl crawl did not return a job id.", response_payload=crawl_payload)
    report["crawl_job_id"] = active_crawl_id

    with session_factory() as db:
        for payload in _iter_crawl_payloads(
            client,
            active_crawl_id,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
        ):
            report["crawl_status"] = payload.get("status")
            report["credits_used"] = payload.get("creditsUsed") or report["credits_used"]
            for document in documents_from_payload(payload):
                normalized = normalize_url(document.url)
                if normalized in documents_seen:
                    continue
                documents_seen.add(normalized)
                processed[_save_firecrawl_document(db, document, domain=domain, discovery_source="firecrawl_crawl", skip_existing=skip_existing)] += 1
                db.commit()
                if sum(processed.values()) >= limit:
                    break
            if sum(processed.values()) >= limit:
                break

        remaining = max(0, limit - sum(processed.values()))
        if remaining:
            for row in _pending_firecrawl_rows(db, domain=domain, limit=remaining):
                status = _scrape_pending_url(db, client, row, domain=domain, skip_existing=skip_existing)
                processed[status] += 1
                db.commit()

        report["processed"] = dict(processed)
        report.update(_db_counts(db, domain))
    _write_report(report)
    return report


def _iter_crawl_payloads(
    client: FirecrawlClient,
    crawl_id: str,
    *,
    poll_interval_seconds: float,
    max_wait_seconds: int,
):
    deadline = time.monotonic() + max(1, max_wait_seconds)
    seen_next: set[str] = set()
    while True:
        try:
            payload = client.get_crawl_status(crawl_id)
        except FirecrawlAPIError as exc:
            if time.monotonic() >= deadline:
                logger.warning("Firecrawl crawl %s status polling timed out: %s", crawl_id, exc)
                return
            logger.warning("Firecrawl crawl %s status polling failed; retrying: %s", crawl_id, exc)
            time.sleep(max(poll_interval_seconds, 0.1))
            continue
        yield payload
        next_url = payload.get("next")
        while isinstance(next_url, str) and next_url and next_url not in seen_next:
            try:
                page_payload = client.get_crawl_status(next_url)
            except FirecrawlAPIError as exc:
                logger.warning("Firecrawl crawl %s pagination failed; retrying on next poll: %s", crawl_id, exc)
                break
            seen_next.add(next_url)
            yield page_payload
            next_url = page_payload.get("next")
        status = str(payload.get("status") or "").lower()
        if status == "completed":
            return
        if status == "failed":
            raise FirecrawlAPIError("Firecrawl crawl failed.", response_payload=payload)
        if time.monotonic() >= deadline:
            logger.warning("Firecrawl crawl %s timed out locally; persisted available partial data.", crawl_id)
            return
        time.sleep(max(poll_interval_seconds, 0.1))


def _pending_firecrawl_rows(db: Session, *, domain: str, limit: int) -> list[DiscoveredURL]:
    rows = (
        db.query(DiscoveredURL)
        .filter(DiscoveredURL.is_allowed.is_(True), DiscoveredURL.indexed.is_(False))
        .order_by(DiscoveredURL.discovered_at.asc())
        .limit(limit * 3)
        .all()
    )
    return [row for row in rows if is_pending(row) and validate_url_scope(row.normalized_url or row.url, domain).is_allowed][:limit]


def _scrape_pending_url(
    db: Session,
    client: FirecrawlClient,
    row: DiscoveredURL,
    *,
    domain: str,
    skip_existing: bool,
) -> str:
    normalized = normalize_url(row.normalized_url or row.url)
    if skip_existing and source_has_chunks(db, normalized):
        mark_indexed(row, final_url=normalized)
        return "skipped_existing"
    if not can_fetch(normalized):
        mark_terminal(row, reason="robots_disallowed", final_url=normalized)
        return "terminal"
    try:
        payload = client.scrape(normalized, zero_data_retention=get_settings().firecrawl_zero_data_retention)
    except FirecrawlAPIError as exc:
        mark_retryable_failure(row, reason="firecrawl_scrape_failed", error=str(exc), http_status=exc.status_code, final_url=normalized)
        return "retryable_failed"
    documents = documents_from_payload(payload)
    if not documents:
        mark_terminal(row, reason="empty_content", final_url=normalized)
        return "empty"
    status = "empty"
    for document in documents:
        status = _save_firecrawl_document(db, document, domain=domain, discovery_source="firecrawl_scrape", skip_existing=skip_existing)
    return status


def verify_firecrawl(domain: str = "mercubuana.ac.id", *, write_report: bool = True) -> dict:
    session_factory = get_session_local()
    with session_factory() as db:
        report = complete_audit(domain, write_report=False)
        report.update(_db_counts(db, domain))
        report["firecrawl_sources_total"] = db.query(Source).filter(Source.discovery_source.like("firecrawl%")).count()
        report["firecrawl_discovered_urls_total"] = db.query(DiscoveredURL).filter(DiscoveredURL.discovery_source.like("firecrawl%")).count()
    if write_report:
        _write_report(report)
    return report


def _db_counts(db: Session, domain: str) -> dict:
    allowed_total = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(True)).count()
    rejected_total = db.query(DiscoveredURL).filter(DiscoveredURL.is_allowed.is_(False)).count()
    indexed_total = db.query(Source).filter(Source.status == "indexed").count()
    chunks_total = db.query(Chunk).count()
    unsafe_indexed = db.query(Source).filter(Source.status == "indexed").all()
    unsafe_count = sum(1 for source in unsafe_indexed if not validate_url_scope(source.url, domain).is_allowed)
    by_source_type = {
        source_type or "unknown": int(count)
        for source_type, count in db.query(Chunk.source_type, func.count(Chunk.id)).group_by(Chunk.source_type).all()
    }
    return {
        "allowed_discovered_urls_total": allowed_total,
        "rejected_discovered_urls_total": rejected_total,
        "indexed_sources_total": indexed_total,
        "chunks_total": chunks_total,
        "unsafe_indexed_sources_total": unsafe_count,
        "source_type_distribution": by_source_type,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Firecrawl-backed UMB knowledge-base ingestion")
    sub = parser.add_subparsers(dest="command", required=True)

    discover_parser = sub.add_parser("discover")
    discover_parser.add_argument("--domain", default="mercubuana.ac.id")
    discover_parser.add_argument("--confirm-authorized", action="store_true")
    discover_parser.add_argument("--limit", type=int, default=None)

    run_parser = sub.add_parser("run")
    run_parser.add_argument("--domain", default="mercubuana.ac.id")
    run_parser.add_argument("--confirm-authorized", action="store_true")
    run_parser.add_argument("--crawl-id", default=None, help="Resume an existing Firecrawl crawl job instead of starting a new one")
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument("--poll-interval", type=float, default=None)
    run_parser.add_argument("--max-wait-seconds", type=int, default=None)
    run_parser.add_argument("--refresh-existing", action="store_true")

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--domain", default="mercubuana.ac.id")
    verify_parser.add_argument("--no-write-report", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command == "discover":
        report = discover_firecrawl(
            domain=args.domain,
            confirm_authorized=args.confirm_authorized,
            crawl_id=args.crawl_id,
            limit=args.limit,
        )
    elif args.command == "run":
        report = run_firecrawl_index(
            domain=args.domain,
            confirm_authorized=args.confirm_authorized,
            limit=args.limit,
            skip_existing=not args.refresh_existing,
            poll_interval_seconds=args.poll_interval,
            max_wait_seconds=args.max_wait_seconds,
        )
    elif args.command == "verify":
        report = verify_firecrawl(args.domain, write_report=not args.no_write_report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report.get("verification_passed", False) else 1
    else:
        raise SystemExit("Unknown command")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
