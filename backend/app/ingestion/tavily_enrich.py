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

# Seeds focused on INFORMATIONAL content (not the already-huge repository/journal corpora):
# the main domain + every faculty + service unit. Non-existent subdomains just return empty.
DEFAULT_SEEDS = [
    "https://mercubuana.ac.id",
    "https://mercubuana.ac.id/akademik",
    "https://mercubuana.ac.id/fakultas",
    "https://mercubuana.ac.id/program-studi",
    "https://mercubuana.ac.id/penelitian",
    "https://mercubuana.ac.id/kemahasiswaan",
    "https://pendaftaran.mercubuana.ac.id",
    "https://pmb.mercubuana.ac.id",
    # faculties
    "https://feb.mercubuana.ac.id",
    "https://ft.mercubuana.ac.id",
    "https://fikom.mercubuana.ac.id",
    "https://fasilkom.mercubuana.ac.id",
    "https://fdsk.mercubuana.ac.id",
    "https://fpsi.mercubuana.ac.id",
    "https://psikologi.mercubuana.ac.id",
    "https://pascasarjana.mercubuana.ac.id",
    "https://fast.mercubuana.ac.id",
    # services / units (where the answer-gaps are)
    "https://lib.mercubuana.ac.id",
    "https://digilib.mercubuana.ac.id",
    "https://baa.mercubuana.ac.id",
    "https://bak.mercubuana.ac.id",
    "https://ditmawa.mercubuana.ac.id",
    "https://support.mercubuana.ac.id",
    "https://ult.mercubuana.ac.id",
    "https://bti.mercubuana.ac.id",
    "https://sdm.mercubuana.ac.id",
    "https://alumni.mercubuana.ac.id",
    "https://elearning.mercubuana.ac.id",
    "https://sia.mercubuana.ac.id",
    "https://sso.mercubuana.ac.id",
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


def enrich(
    seeds: list[str] | None = None,
    *,
    per_seed: int = 120,
    max_depth: int = 2,
    only_new: bool = True,
    use_map: bool = True,
) -> dict:
    client = TavilyClient()
    client.ensure_configured()
    seeds = seeds or DEFAULT_SEEDS
    db = get_session_local()()
    try:
        existing = _existing_urls(db) if only_new else set()
        stats = {"indexed": 0, "skipped": 0, "chunks": 0}

        def _ingest(pages) -> None:
            for item in pages:
                norm = normalize_url(item.url)
                if only_new and norm in existing:
                    stats["skipped"] += 1
                    continue
                if _is_junk(item.raw_content):
                    stats["skipped"] += 1
                    continue
                try:
                    n = upsert_source_document(
                        db, item.url, item.raw_content, item.title or item.url,
                        {"discovery_source": "tavily_crawl"}, 200,
                        discovery_source="tavily_crawl", extraction_method="tavily_crawl",
                        extraction_confidence=0.92,
                    )
                    db.commit()
                    stats["indexed"] += 1
                    stats["chunks"] += n
                    existing.add(norm)
                except Exception as exc:
                    db.rollback()
                    stats["skipped"] += 1
                    logger.warning("Upsert failed for %s: %s", item.url, exc)

        for seed in seeds:
            # 1) crawl discovers + extracts content in one shot
            try:
                _ingest(client.crawl(seed, max_depth=max_depth, limit=per_seed))
            except Exception as exc:
                logger.warning("Tavily crawl failed for %s: %s", seed, exc)
            # 2) map finds additional in-scope URLs the crawl missed; extract the new ones
            if use_map:
                try:
                    mapped = client.map_site(seed, max_depth=max_depth, limit=per_seed)
                    new_urls = [u for u in mapped if not (only_new and normalize_url(u) in existing)]
                    if new_urls:
                        _ingest(client.extract(new_urls))
                except Exception as exc:
                    logger.warning("Tavily map/extract failed for %s: %s", seed, exc)
            logger.info("seed %s -> indexed=%d skipped=%d chunks=%d",
                        seed, stats["indexed"], stats["skipped"], stats["chunks"])
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Enrich the UMB KB via Tavily crawl+map+extract.")
    parser.add_argument("--per-seed", type=int, default=120)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--no-map", action="store_true", help="crawl only (skip map+extract)")
    parser.add_argument("--all", action="store_true", help="re-extract even if URL already indexed")
    args = parser.parse_args()
    summary = enrich(
        per_seed=args.per_seed, max_depth=args.max_depth, only_new=not args.all, use_map=not args.no_map
    )
    print("DONE", summary)
