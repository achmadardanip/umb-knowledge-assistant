"""Persist web-derived answer contexts into the KB ("Web -> KB ingest").

When the live web retriever supplies contexts that are not yet in the indexed KB,
we write them as Sources + Chunks (reusing the crawl pipeline's upsert) so the next
similar question is served straight from the KB — no second web round-trip and no
LLM call (cache/indexed path). Dedup and content-hash handling are inherited from
``upsert_source_document``; the trust/authority substrate down-weights non-UMB hosts
at retrieval time, so persisting external corroboration does not over-trust it.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.ingestion.pipeline import upsert_source_document

logger = logging.getLogger(__name__)

WEB_ORIGIN = "live_web_search"


def _context_text(ctx: dict) -> str:
    return (ctx.get("chunk_text") or ctx.get("content") or "").strip()


def persist_web_contexts(db: Session, contexts: list[dict]) -> int:
    """Group web contexts by URL and upsert each as a KB Source.

    Returns the number of chunks written (or already present for unchanged content).
    Best-effort: a failure on one URL is logged and skipped, never raised.
    """
    if not contexts:
        return 0

    grouped: "OrderedDict[str, dict]" = OrderedDict()
    for ctx in contexts:
        url = (ctx.get("url") or "").strip()
        text = _context_text(ctx)
        if not url or not text:
            continue
        bucket = grouped.get(url)
        if bucket is None:
            grouped[url] = {
                "title": ctx.get("title") or url,
                "hostname": (ctx.get("hostname") or "").lower(),
                "source_type": ctx.get("source_type") or "html",
                "texts": [text],
            }
        elif text not in bucket["texts"]:
            bucket["texts"].append(text)

    total_chunks = 0
    for url, info in grouped.items():
        text = "\n\n".join(info["texts"])
        try:
            total_chunks += upsert_source_document(
                db,
                url=url,
                text=text,
                title=info["title"],
                metadata={
                    "hostname": info["hostname"],
                    "ingested_via": "web_kb_ingest",
                    "source_type": info["source_type"],
                },
                http_status=200,
                discovery_source="web_kb_ingest",
                min_words=1,
            )
        except Exception as exc:  # pragma: no cover - best-effort persistence
            logger.warning("web_kb_ingest failed for %s: %s", url, exc)
    return total_chunks
