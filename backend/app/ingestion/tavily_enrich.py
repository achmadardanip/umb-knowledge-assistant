"""Tavily-based KB enrichment.

Uses Tavily /map to discover in-scope ``*.mercubuana.ac.id`` URLs, /extract to pull
clean page content, then upserts into the KB through the active embedding profile
(local E5). Error/empty pages are skipped so we don't re-introduce the junk we just
cleaned. Run detached for large crawls:

    python -m app.ingestion.tavily_enrich --max-pages 400 --max-depth 2
"""

from __future__ import annotations

import argparse
import logging

from app.db.database import get_session_local
from app.db.models import Source
from app.discovery.url_normalizer import normalize_url
from app.ingestion.pipeline import upsert_source_document
from app.web_search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)

# Seeds spanning the public UMB surface; Tavily /map fans out within each (in-scope only).
DEFAULT_SEEDS = [
    "https://mercubuana.ac.id",
    "https://pendaftaran.mercubuana.ac.id",
    "https://fasilkom.mercubuana.ac.id",
    "https://baa.mercubuana.ac.id",
    "https://support.mercubuana.ac.id",
    "https://ult.mercubuana.ac.id",
    "https://perpustakaan.mercubuana.ac.id",
    "https://ditmawa.mercubuana.ac.id",
    "https://pksm.mercubuana.ac.id",
]

_ERROR_MARKERS = ("404 not found", "page not found", "tidak ditemukan", "halaman tidak ditemukan", "error 404")


def _existing_urls(db) -> set[str]:
    return {normalize_url(url or "") for (url,) in db.query(Source.url).all()}


def _is_junk(text: str) -> bool:
    body = (text or "").strip()
    if len(body) < 80:
        return True
    head = body[:200].lower()
    return any(marker in head for marker in _ERROR_MARKERS)


def enrich(seeds: list[str] | None = None, *, max_pages: int = 300, max_depth: int = 2, only_new: bool = True) -> dict:
    client = TavilyClient()
    client.ensure_configured()
    seeds = seeds or DEFAULT_SEEDS
    per_seed = max(10, max_pages // len(seeds))
    db = get_session_local()()
    try:
        existing = _existing_urls(db) if only_new else set()
        indexed = skipped = chunks = 0
        for seed in seeds:
            try:
                pages = client.crawl(seed, max_depth=max_depth, limit=per_seed)
            except Exception as exc:  # one bad seed must not abort the run
                logger.warning("Tavily crawl failed for %s: %s", seed, exc)
                continue
            for item in pages:
                if only_new and normalize_url(item.url) in existing:
                    skipped += 1
                    continue
                if _is_junk(item.raw_content):
                    skipped += 1
                    continue
                try:
                    n = upsert_source_document(
                        db,
                        item.url,
                        item.raw_content,
                        item.title or item.url,
                        {"discovery_source": "tavily_crawl"},
                        200,
                        discovery_source="tavily_crawl",
                        extraction_method="tavily_crawl",
                        extraction_confidence=0.92,
                    )
                    db.commit()
                    indexed += 1
                    chunks += n
                    existing.add(normalize_url(item.url))
                except Exception as exc:
                    db.rollback()
                    skipped += 1
                    logger.warning("Upsert failed for %s: %s", item.url, exc)
            logger.info("seed %s -> indexed=%d skipped=%d chunks=%d", seed, indexed, skipped, chunks)
        return {"indexed": indexed, "skipped": skipped, "chunks": chunks}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Enrich the UMB KB via Tavily map+extract.")
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--all", action="store_true", help="re-extract even if URL already indexed")
    args = parser.parse_args()
    summary = enrich(max_pages=args.max_pages, max_depth=args.max_depth, only_new=not args.all)
    print("DONE", summary)
