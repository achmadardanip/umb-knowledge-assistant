"""Phase 19 P19.1 — autonomous incremental crawler *worker*.

One worker pass:

    due_urls(frequency) -> for each url:
        fetch (conditional) -> detect_changed_content()
            changed   -> re-ingest (re-chunk + re-embed + graph/freshness) , record_crawl(changed)
            unchanged -> bump verification timestamp           , record_crawl(skipped)

Design properties:
  * crash-safe / resumable — state lives in crawl_registry; each URL is committed
    independently (record_crawl), so a restart resumes from where it stopped and
    never loses progress;
  * duplicate-safe — unchanged pages are skipped (no re-ingest -> no new chunks);
    re-ingest goes through the existing idempotent upsert pipeline keyed by URL;
  * pluggable fetcher — ``HttpFetcher`` for live runs, ``VerifyFetcher`` (no
    network, replays the stored hash) for deterministic runtime validation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crawl.incremental import content_hash, detect_changed_content, due_urls, record_crawl

logger = logging.getLogger("umb.crawler")


@dataclass
class FetchResult:
    url: str
    ok: bool
    new_hash: str | None = None
    last_modified: datetime | None = None
    http_status: int | None = None
    content_type: str | None = None
    body: str | None = None
    error: str | None = None


class Fetcher(Protocol):
    def fetch(self, db: Session, url: str) -> FetchResult: ...


class VerifyFetcher:
    """No-network fetcher used for runtime validation: replays the hash already in
    the registry (i.e. simulates an unchanged page). ``mutate`` URLs are returned
    with a perturbed hash to simulate a real change."""

    def __init__(self, mutate: set[str] | None = None) -> None:
        self.mutate = mutate or set()

    def fetch(self, db: Session, url: str) -> FetchResult:
        row = db.execute(text("SELECT content_hash, content_type FROM crawl_registry WHERE url=:u"), {"u": url}).first()
        h = (row[0] if row else None) or content_hash(url)
        ctype = (row[1] if row else None) or "html"
        if url in self.mutate:
            h = content_hash(h + "::changed")
        return FetchResult(url=url, ok=True, new_hash=h, http_status=200, content_type=ctype)


class HttpFetcher:
    """Live conditional fetch. Uses If-Modified-Since when we have a prior crawl so
    the server can answer 304 (cheap skip). Best-effort — network errors degrade to
    a failed FetchResult (the worker records the failure and moves on)."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def fetch(self, db: Session, url: str) -> FetchResult:
        try:
            import httpx
        except Exception:  # pragma: no cover
            return FetchResult(url=url, ok=False, error="httpx not installed")
        prev = db.execute(
            text("SELECT last_crawl, last_modified FROM crawl_registry WHERE url=:u"), {"u": url}
        ).first()
        headers = {}
        if prev and prev[1]:
            headers["If-Modified-Since"] = prev[1].strftime("%a, %d %b %Y %H:%M:%S GMT")
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code == 304:
                return FetchResult(url=url, ok=True, new_hash=(prev and prev[1] and None), http_status=304)
            lm = None
            if "Last-Modified" in resp.headers:
                try:
                    lm = datetime.strptime(resp.headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
                except Exception:
                    lm = None
            ctype = "pdf" if url.lower().endswith(".pdf") or "pdf" in resp.headers.get("content-type", "") else "html"
            return FetchResult(url=url, ok=resp.status_code < 400, new_hash=content_hash(resp.content),
                               last_modified=lm, http_status=resp.status_code, content_type=ctype,
                               body=None if ctype == "pdf" else resp.text)
        except Exception as e:
            return FetchResult(url=url, ok=False, error=str(e)[:120])


def _default_reingest(urls: list[str]) -> dict:
    """Re-ingest changed URLs through the existing idempotent pipeline (fetch +
    chunk + embed + upsert keyed by URL). Imported lazily so worker import is cheap."""
    from app.ingestion.pipeline import crawl_and_index_urls

    return crawl_and_index_urls(urls, max_pages=len(urls), rate_limit=1.0)


def process_url(
    db: Session,
    url: str,
    fetcher: Fetcher,
    *,
    reingest: Callable[[list[str]], dict] | None = None,
    apply_reingest: bool = True,
) -> dict:
    """Process one URL. Returns a per-URL outcome dict. Never raises — failures are
    recorded so the worker stays crash-safe."""
    try:
        res = fetcher.fetch(db, url)
        if not res.ok:
            record_crawl(db, url, status="failed", http_status=res.http_status, changed=False)
            return {"url": url, "outcome": "failed", "reason": res.error}
        if res.http_status == 304 or res.new_hash is None:
            # server says not modified — just bump verification.
            record_crawl(db, url, status="skipped", http_status=res.http_status, changed=False)
            _bump_source_verified(db, url)
            return {"url": url, "outcome": "skipped", "reason": "not_modified"}

        decision = detect_changed_content(db, url, new_hash=res.new_hash, last_modified=res.last_modified)
        if decision.changed:
            reingested = False
            if apply_reingest:
                (reingest or _default_reingest)([url])
                reingested = True
            record_crawl(db, url, new_hash=res.new_hash, last_modified=res.last_modified,
                         http_status=res.http_status, content_type=res.content_type,
                         status="crawled", changed=True)
            _bump_source_verified(db, url, fetched=True)
            return {"url": url, "outcome": "reingested" if reingested else "changed_detected", "reason": decision.reason}
        else:
            record_crawl(db, url, new_hash=res.new_hash, last_modified=res.last_modified,
                         http_status=res.http_status, content_type=res.content_type,
                         status="skipped", changed=False)
            _bump_source_verified(db, url)
            return {"url": url, "outcome": "skipped", "reason": "unchanged"}
    except Exception as e:  # pragma: no cover - defensive
        try:
            record_crawl(db, url, status="failed", changed=False)
        except Exception:
            db.rollback()
        return {"url": url, "outcome": "failed", "reason": str(e)[:120]}


def _bump_source_verified(db: Session, url: str, fetched: bool = False) -> None:
    """Update source freshness: always bump last_verified_date; on a real re-fetch
    also bump fetched_at (the crawl_date)."""
    try:
        if fetched:
            db.execute(text("UPDATE sources SET last_verified_date=now(), fetched_at=now() WHERE url=:u"), {"u": url})
        else:
            db.execute(text("UPDATE sources SET last_verified_date=now() WHERE url=:u"), {"u": url})
        db.commit()
    except Exception:
        db.rollback()


def run_worker(
    db: Session,
    *,
    frequency: str | None = None,
    fetcher: Fetcher | None = None,
    limit: int = 200,
    apply_reingest: bool = True,
    reingest: Callable[[list[str]], dict] | None = None,
) -> dict:
    """Run one worker pass over the due URLs for ``frequency``. Returns aggregate
    stats including before/after chunk counts (duplicate-growth guard)."""
    fetcher = fetcher or HttpFetcher()
    chunks_before = db.execute(text("SELECT count(*) FROM chunks")).scalar()
    urls = due_urls(db, frequency=frequency, limit=limit)
    started = time.time()
    counts = {"reingested": 0, "skipped": 0, "failed": 0, "changed_detected": 0}
    per_url: list[dict] = []
    for url in urls:
        out = process_url(db, url, fetcher, reingest=reingest, apply_reingest=apply_reingest)
        counts[out["outcome"]] = counts.get(out["outcome"], 0) + 1
        per_url.append(out)
        logger.info("crawl %s -> %s (%s)", url, out["outcome"], out.get("reason"))
    chunks_after = db.execute(text("SELECT count(*) FROM chunks")).scalar()
    return {
        "frequency": frequency or "all",
        "due": len(urls),
        "processed": len(per_url),
        "counts": counts,
        "chunks_before": chunks_before,
        "chunks_after": chunks_after,
        "duplicate_chunk_growth": max(0, chunks_after - chunks_before) - counts["reingested"] * 0,
        "elapsed_sec": round(time.time() - started, 2),
        "sample": per_url[:20],
    }
