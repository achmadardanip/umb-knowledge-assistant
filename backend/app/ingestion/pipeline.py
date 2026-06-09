from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.paths import project_path
from app.crawler.crawler import crawl_bfs, fetch_page
from app.crawler.extractor import content_hash
from app.db.database import get_session_local
from app.db.models import Chunk, DiscoveredURL, Document, Source, utcnow
from app.discovery.robots_checker import can_fetch
from app.discovery.scope_validator import validate_url_scope
from app.discovery.url_normalizer import normalize_url
from app.ingestion.chunker import chunk_text
from app.ingestion.embedder import EmbeddingConfigurationError, get_embedder
from app.ingestion.embedding_store import ensure_embedding_storage, store_chunk_embedding, validate_embedding_batch
from app.ingestion.index_state import is_terminal, mark_indexed, mark_retryable_failure, mark_terminal, source_has_chunks


logger = logging.getLogger(__name__)

FILTERED_URLS = project_path("data", "discovery", "urls_filtered.txt")
DISCOVERY_REPORT = project_path("data", "discovery", "discovery_report.json")


def _upsert_discovered_url(db: Session, url: str, *, discovery_source: str, is_allowed: bool, rejection_reason: str | None = None) -> DiscoveredURL:
    normalized_url = normalize_url(url)
    parsed = urlparse(normalized_url)
    existing = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalized_url).first()
    if existing is None:
        existing = DiscoveredURL(url=normalized_url, normalized_url=normalized_url)
        db.add(existing)
    existing.hostname = (parsed.hostname or "").lower()
    existing.path = parsed.path or "/"
    existing.discovery_source = existing.discovery_source or discovery_source
    existing.is_allowed = is_allowed
    existing.rejection_reason = rejection_reason
    return existing


def upsert_source_document(
    db: Session,
    url: str,
    text: str,
    title: str | None,
    metadata: dict,
    http_status: int,
    discovery_source: str | None = None,
    min_words: int = 25,
    source_type: str = "html",
    extraction_method: str = "trafilatura+beautifulsoup",
    extraction_confidence: float = 0.9,
) -> int:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    existing = db.query(Source).filter(Source.url == url).first()
    if existing is None:
        existing = Source(url=url)
        db.add(existing)
        db.flush()
    new_hash = content_hash(text)
    if existing.status == "indexed" and existing.content_hash == new_hash:
        existing.fetched_at = utcnow()
        existing.http_status = http_status
        existing.discovery_source = discovery_source or existing.discovery_source
        return max(db.query(Chunk).filter(Chunk.source_id == existing.id).count(), 1)
    if existing.id:
        db.query(Chunk).filter(Chunk.source_id == existing.id, Chunk.asset_id.is_(None)).delete(synchronize_session=False)
        db.query(Document).filter(Document.source_id == existing.id).delete(synchronize_session=False)
    existing.hostname = hostname
    existing.path = path
    existing.discovery_source = discovery_source or existing.discovery_source
    existing.title = title
    existing.content_hash = new_hash
    existing.status = "indexed" if text else "empty"
    existing.http_status = http_status
    document = Document(source_id=existing.id, raw_text=text, cleaned_text=text)
    db.add(document)
    db.flush()

    try:
        embedder = get_embedder()
    except EmbeddingConfigurationError:
        embedder = None
    chunk_metadata = {
        **(metadata or {}),
        "url": url,
        "hostname": hostname,
        "path": path,
        "title": title,
        "source_type": source_type,
        "discovery_source": discovery_source,
        "extraction_method": extraction_method,
        "extraction_confidence": extraction_confidence,
    }
    chunks = chunk_text(
        text,
        metadata=chunk_metadata,
        chunk_size=get_settings().chunk_size,
        overlap=get_settings().chunk_overlap,
        min_words=min_words,
    )
    if not chunks:
        existing.status = "empty"
        return 0

    embeddings = [None] * len(chunks)
    if embedder and chunks:
        try:
            embeddings = embedder.embed_texts([chunk.chunk_text for chunk in chunks])
            validate_embedding_batch(embedder, embeddings, len(chunks))
            ensure_embedding_storage(db, embedder)
        except Exception as exc:
            logger.warning("Embedding failed for %s; indexing keyword-only chunks: %s", url, exc)
            embeddings = [None] * len(chunks)
    for chunk, embedding in zip(chunks, embeddings, strict=True):
        chunk_row = Chunk(
            document_id=document.id,
            source_id=existing.id,
            chunk_text=chunk.chunk_text,
            chunk_index=chunk.chunk_index,
            token_count=chunk.token_count,
            meta=chunk.metadata,
            source_type=chunk.source_type,
            extraction_method=chunk.extraction_method,
            extraction_confidence=chunk.extraction_confidence,
        )
        db.add(chunk_row)
        if embedding is not None:
            store_chunk_embedding(db, chunk_row, embedding, embedder)
    return len(chunks)


def _source_type_distribution(db: Session) -> dict[str, int]:
    rows = db.query(Chunk.source_type, func.count(Chunk.id)).group_by(Chunk.source_type).all()
    return {source_type or "unknown": int(count) for source_type, count in rows}


def _update_discovery_report(report_update: dict) -> None:
    report = {}
    if DISCOVERY_REPORT.exists():
        try:
            report = json.loads(DISCOVERY_REPORT.read_text(encoding="utf-8"))
        except Exception:
            report = {}
    report.update(report_update)
    DISCOVERY_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def crawl_and_index_urls(urls: list[str], *, max_pages: int, rate_limit: float) -> dict:
    settings = get_settings()
    session_factory = get_session_local()
    indexed = 0
    skipped = 0
    failed = 0
    delay = 1.0 / max(rate_limit, 0.1)
    with session_factory() as db:
        indexed_total = db.query(Source).filter(Source.status == "indexed").count()
        target = max(1, settings.index_target_sources)
        for url in urls:
            if indexed + skipped + failed >= max_pages or indexed_total >= target:
                break
            decision = validate_url_scope(url, settings.allowed_domain)
            if not decision.is_allowed:
                skipped += 1
                continue
            discovered = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == url).first()
            discovery_source = discovered.discovery_source if discovered else None
            existing_exact = db.query(Source).filter(Source.url == url, Source.status == "indexed").first()
            if existing_exact or (discovered and discovered.indexed):
                if existing_exact and source_has_chunks(db, existing_exact.url):
                    if discovered:
                        mark_indexed(discovered)
                    db.commit()
                    skipped += 1
                    continue
                if discovered:
                    discovered.indexed = False
            if discovered and is_terminal(discovered):
                skipped += 1
                continue
            page = fetch_page(url, timeout=settings.crawler_timeout_seconds)
            time.sleep(delay)
            if not page:
                failed += 1
                if discovered:
                    mark_retryable_failure(discovered, reason="fetch_failed", error="empty_or_unreachable")
                db.commit()
                continue
            if not page.text:
                failed += 1
                if discovered:
                    content_type = page.metadata.get("content_type")
                    reason = "empty_content"
                    if page.status_code in {401, 403, 404}:
                        reason = f"http_{page.status_code}"
                    elif page.status_code >= 400:
                        reason = "http_error"
                    elif content_type:
                        reason = "unsupported_content_type"
                    mark_terminal(discovered, reason=reason, http_status=page.status_code, final_url=page.url, content_type=content_type)
                db.commit()
                continue
            existing_source = db.query(Source).filter(Source.url == page.url, Source.status == "indexed").first()
            if existing_source and source_has_chunks(db, existing_source.url):
                if discovered:
                    mark_indexed(discovered, http_status=page.status_code, final_url=page.url)
                db.commit()
                skipped += 1
                continue
            chunks = upsert_source_document(
                db,
                page.url,
                page.text,
                page.title,
                page.metadata,
                page.status_code,
                discovery_source=discovery_source,
            )
            if discovered:
                if chunks > 0:
                    mark_indexed(discovered, http_status=page.status_code, final_url=page.url)
                else:
                    mark_terminal(discovered, reason="empty_content", http_status=page.status_code, final_url=page.url)
            indexed += 1
            if chunks > 0:
                indexed_total += 1
            db.commit()
        report = {
            "pages_indexed": indexed,
            "pages_skipped": skipped,
            "crawl_failed_total": failed,
            "index_target_sources": settings.index_target_sources,
            "indexed_sources_total": db.query(Source).filter(Source.status == "indexed").count(),
            "chunks_total": db.query(Chunk).count(),
            "source_type_distribution": _source_type_distribution(db),
            "last_indexed_at": utcnow().isoformat(),
        }
    _update_discovery_report(report)
    return report


def crawl_discovered(max_pages: int = 500, rate_limit: float = 2.0) -> dict:
    urls: list[str] = []
    if FILTERED_URLS.exists():
        urls = [line.strip() for line in FILTERED_URLS.read_text(encoding="utf-8").splitlines() if line.strip()]
        try:
            session_factory = get_session_local()
            with session_factory() as db:
                unfinished: list[str] = []
                for index in range(0, len(urls), 1000):
                    batch = urls[index : index + 1000]
                    rows = (
                        db.query(DiscoveredURL.normalized_url, DiscoveredURL.crawled_at, DiscoveredURL.indexed, DiscoveredURL.meta)
                        .filter(DiscoveredURL.normalized_url.in_(batch))
                        .all()
                    )
                    status_by_url = {row.normalized_url: row for row in rows}
                    for url in batch:
                        row = status_by_url.get(url)
                        if row is None or (not row.indexed and not is_terminal(row)):
                            unfinished.append(url)
                urls = unfinished
        except Exception:
            pass
        return crawl_and_index_urls(urls, max_pages=max_pages, rate_limit=rate_limit)

    try:
        session_factory = get_session_local()
        with session_factory() as db:
            rows = (
                db.query(DiscoveredURL)
                .filter(DiscoveredURL.is_allowed.is_(True), DiscoveredURL.indexed.is_(False))
                .limit(max_pages)
                .all()
            )
            urls = [row.normalized_url or row.url for row in rows if not is_terminal(row)]
    except Exception:
        urls = []

    if not urls:
        if not FILTERED_URLS.exists():
            return {"pages_indexed": 0, "pages_skipped": 0, "reason": "data/discovery/urls_filtered.txt not found"}
        urls = [line.strip() for line in FILTERED_URLS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return crawl_and_index_urls(urls, max_pages=max_pages, rate_limit=rate_limit)


def crawl_domain(domain: str, max_pages: int = 500, max_depth: int = 3, confirm_authorized: bool = False) -> dict:
    if not confirm_authorized:
        raise SystemExit("Crawling a real domain requires --confirm-authorized.")
    settings = get_settings()
    session_factory = get_session_local()
    start = normalize_url(f"https://{domain}")
    queue = deque([(start, 0)])
    seen = {start}
    indexed = 0
    skipped = 0
    discovered_count = 0
    recorded_urls: set[str] = set()
    delay = 1.0 / max(settings.discovery_rate_limit, 0.1)

    with session_factory() as db:
        def record_url(url_to_record: str, *, is_allowed: bool, rejection_reason: str | None = None) -> DiscoveredURL | None:
            normalized = normalize_url(url_to_record)
            if normalized in recorded_urls:
                return None
            recorded_urls.add(normalized)
            return _upsert_discovered_url(
                db,
                normalized,
                discovery_source="internal_crawler",
                is_allowed=is_allowed,
                rejection_reason=rejection_reason,
            )

        while queue and indexed + skipped < max_pages:
            url, depth = queue.popleft()
            decision = validate_url_scope(url, domain)
            if not decision.is_allowed:
                record_url(url, is_allowed=False, rejection_reason=decision.reason)
                db.commit()
                skipped += 1
                continue
            discovered = record_url(url, is_allowed=True)
            if discovered is None:
                discovered = db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url == normalize_url(url)).first()
            if not can_fetch(url):
                if discovered:
                    mark_terminal(discovered, reason="robots_disallowed")
                db.commit()
                skipped += 1
                continue

            page = fetch_page(url, timeout=settings.crawler_timeout_seconds)
            time.sleep(delay)
            if not page:
                if discovered:
                    mark_retryable_failure(discovered, reason="fetch_failed", error="empty_or_unreachable")
                db.commit()
                skipped += 1
                continue
            if not page.text:
                if discovered:
                    content_type = page.metadata.get("content_type")
                    reason = "empty_content"
                    if page.status_code in {401, 403, 404}:
                        reason = f"http_{page.status_code}"
                    elif page.status_code >= 400:
                        reason = "http_error"
                    elif content_type:
                        reason = "unsupported_content_type"
                    mark_terminal(discovered, reason=reason, http_status=page.status_code, final_url=page.url, content_type=content_type)
                db.commit()
                skipped += 1
                continue

            for link in page.links:
                link_decision = validate_url_scope(link, domain)
                if record_url(link, is_allowed=link_decision.is_allowed, rejection_reason=None if link_decision.is_allowed else link_decision.reason):
                    discovered_count += 1
                if depth < max_depth and link_decision.is_allowed and link not in seen:
                    seen.add(link)
                    queue.append((link, depth + 1))

            existing_source = db.query(Source).filter(Source.url == page.url, Source.status == "indexed").first()
            if existing_source and source_has_chunks(db, existing_source.url):
                mark_indexed(discovered, http_status=page.status_code, final_url=page.url)
                db.commit()
                skipped += 1
                continue

            chunks = upsert_source_document(
                db,
                page.url,
                page.text,
                page.title,
                page.metadata,
                page.status_code,
                discovery_source=discovered.discovery_source,
            )
            if chunks > 0:
                mark_indexed(discovered, http_status=page.status_code, final_url=page.url)
            else:
                mark_terminal(discovered, reason="empty_content", http_status=page.status_code, final_url=page.url)
            indexed += 1
            db.commit()

    return {"pages_indexed": indexed, "pages_skipped": skipped, "urls_seen": len(seen), "urls_discovered": discovered_count}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UMB ingestion pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    discovered = sub.add_parser("crawl-discovered")
    discovered.add_argument("--max-pages", type=int, default=get_settings().crawler_max_pages)
    discovered.add_argument("--rate-limit", type=float, default=get_settings().crawler_rate_limit)

    crawl = sub.add_parser("crawl")
    crawl.add_argument("--domain", default="mercubuana.ac.id")
    crawl.add_argument("--max-pages", type=int, default=get_settings().crawler_max_pages)
    crawl.add_argument("--max-depth", type=int, default=3)
    crawl.add_argument("--confirm-authorized", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "crawl-discovered":
        report = crawl_discovered(max_pages=args.max_pages, rate_limit=args.rate_limit)
    elif args.command == "crawl":
        report = crawl_domain(args.domain, max_pages=args.max_pages, max_depth=args.max_depth, confirm_authorized=args.confirm_authorized)
    else:
        raise SystemExit("Unknown command")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
