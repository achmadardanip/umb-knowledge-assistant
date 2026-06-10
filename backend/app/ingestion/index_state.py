from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.db.models import Chunk, DiscoveredURL, Source, utcnow


TERMINAL_REASONS = {
    "http_401",
    "http_403",
    "http_404",
    "http_error",
    "robots_disallowed",
    "empty_content",
    "unsupported_content_type",
    "file_too_large",
    "download_failed",
    "extraction_failed",
    "unsafe_scope",
    "transient_failure",
}


def metadata_for(row: DiscoveredURL | None) -> dict:
    return dict((row.meta if row else None) or {})


def attempt_count(row: DiscoveredURL | None) -> int:
    meta = metadata_for(row)
    try:
        return int(meta.get("attempt_count") or 0)
    except (TypeError, ValueError):
        return 0


def is_terminal(row: DiscoveredURL | None) -> bool:
    meta = metadata_for(row)
    return meta.get("crawl_status") == "terminal" or bool(meta.get("terminal_reason"))


def is_pending(row: DiscoveredURL) -> bool:
    return bool(row.is_allowed) and not bool(row.indexed) and not is_terminal(row)


def mark_retryable_failure(
    row: DiscoveredURL,
    *,
    reason: str,
    error: str | None = None,
    http_status: int | None = None,
    final_url: str | None = None,
    content_type: str | None = None,
) -> None:
    meta = metadata_for(row)
    meta.update(
        {
            "crawl_status": "retryable_failed",
            "attempt_count": attempt_count(row) + 1,
            "last_error": error or reason,
        }
    )
    if final_url:
        meta["final_url"] = final_url
    if content_type:
        meta["content_type"] = content_type
    row.meta = meta
    row.crawled_at = utcnow()
    row.indexed = False
    if http_status is not None:
        row.http_status = http_status


def mark_terminal(
    row: DiscoveredURL,
    *,
    reason: str,
    error: str | None = None,
    http_status: int | None = None,
    final_url: str | None = None,
    content_type: str | None = None,
    extra: Mapping | None = None,
) -> None:
    meta = metadata_for(row)
    meta.update(
        {
            "crawl_status": "terminal",
            "terminal_reason": reason,
            "attempt_count": attempt_count(row) + 1,
        }
    )
    if error:
        meta["last_error"] = error
    if final_url:
        meta["final_url"] = final_url
    if content_type:
        meta["content_type"] = content_type
    if extra:
        meta.update(dict(extra))
    row.meta = meta
    row.crawled_at = utcnow()
    row.indexed = False
    row.rejection_reason = row.rejection_reason or reason
    if http_status is not None:
        row.http_status = http_status


def mark_indexed(row: DiscoveredURL, *, http_status: int | None = None, final_url: str | None = None, content_type: str | None = None) -> None:
    meta = metadata_for(row)
    meta.pop("terminal_reason", None)
    meta.update({"crawl_status": "indexed", "attempt_count": attempt_count(row) + 1})
    if final_url:
        meta["final_url"] = final_url
    if content_type:
        meta["content_type"] = content_type
    row.meta = meta
    row.indexed = True
    row.crawled_at = utcnow()
    row.rejection_reason = None
    if http_status is not None:
        row.http_status = http_status


def source_has_chunks(db: Session, url: str) -> bool:
    source = db.query(Source).filter(Source.url == url, Source.status == "indexed").first()
    if source is None:
        return False
    return db.query(Chunk.id).filter(Chunk.source_id == source.id).first() is not None
