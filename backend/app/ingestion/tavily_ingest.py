"""Tavily-first discovery + extraction ingest for the UMB knowledge base.

Uses Tavily as the primary discovery layer (map + site-scoped search) to build a
URL map of ``mercubuana.ac.id`` and its official subdomains, then Tavily Extract to
pull clean content, and finally reuses the existing chunk -> embed (local E5) ->
store pipeline (:func:`app.ingestion.pipeline.upsert_source_document`).

This path does not depend on Firecrawl. Run the knowledge-graph rebuild
(``python -m app.graph.build_graph``) afterwards so relation-aware retrieval stays
current.

Usage::

    python -m app.ingestion.tavily_ingest map --confirm-authorized
    python -m app.ingestion.tavily_ingest ingest --limit 500 --confirm-authorized
    python -m app.ingestion.tavily_ingest run-all --limit 500 --confirm-authorized
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone

from app.core.logging import configure_logging
from app.core.paths import project_path
from app.db.database import get_session_local
from app.db.models import Source
from app.discovery.scope_validator import validate_url_scope
from app.ingestion.index_state import source_has_chunks
from app.ingestion.pipeline import upsert_source_document
from app.ingestion.umb_content import (
    canonicalize_umb_url,
    classify_umb_url,
    clean_umb_content,
    filename_title,
)
from app.web_search.tavily_client import TavilyClient

logger = logging.getLogger(__name__)

URL_MAP_PATH = project_path("data", "discovery", "tavily_url_map.json")
INGEST_REPORT_PATH = project_path("data", "reports", "tavily_ingest.json")

# Root domains to map first. Subdomains are still scope-allowed by the validator and
# surface through site-scoped search even when not listed explicitly here.
MAP_ROOTS = (
    "https://www.mercubuana.ac.id",
    "https://mercubuana.ac.id",
    "https://lib.mercubuana.ac.id",
    "https://repository.mercubuana.ac.id",
    "https://fasilkom.mercubuana.ac.id",
    "https://pendaftaran.mercubuana.ac.id",
)

# Category-aligned seed queries spanning the assistant's required coverage.
SEED_QUERIES = (
    "profil universitas sejarah visi misi rektor",
    "struktur organisasi pimpinan universitas",
    "lokasi kampus Meruya Menteng Warung Buncit",
    "akreditasi institusi program studi",
    "kerjasama industri mitra",
    "fakultas dan program studi sarjana magister doktor",
    "fakultas teknik ekonomi bisnis ilmu komunikasi psikologi desain",
    "fakultas ilmu komputer informatika sistem informasi",
    "dekan dosen tenaga kependidikan profil",
    "kurikulum mata kuliah program studi",
    "pendaftaran mahasiswa baru PMB jalur seleksi",
    "biaya kuliah uang kuliah rincian pembayaran",
    "kelas reguler kelas karyawan kelas internasional",
    "kalender akademik jadwal kuliah semester",
    "pedoman akademik panduan akademik mahasiswa",
    "pengumuman akademik informasi terbaru",
    "biro administrasi akademik BAA layanan",
    "beasiswa mahasiswa bantuan pendidikan",
    "kemahasiswaan organisasi unit kegiatan mahasiswa",
    "layanan mahasiswa karir alumni",
    "berita kabar kampus kegiatan acara",
    "perpustakaan layanan bebas pustaka koleksi",
    "repository karya ilmiah skripsi tesis disertasi",
    "jurnal publikasi ilmiah proceeding",
    "lembaga penjaminan mutu LPM",
    "keselamatan kesehatan kerja K3LK laporan",
    "fasilitas kampus laboratorium",
    "satgas pencegahan kekerasan PPK",
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def discover(*, per_query: int, map_limit: int, map_depth: int) -> dict[str, dict]:
    """Run Tavily map + search discovery and return ``{canonical_url: hint}``."""

    client = TavilyClient()
    client.ensure_configured()
    discovered: dict[str, dict] = {}

    def _add(url: str, *, source: str, title: str | None = None, score: float = 0.0) -> None:
        canonical = canonicalize_umb_url(url)
        if not validate_url_scope(canonical, client.strict_domain).is_allowed:
            return
        existing = discovered.get(canonical)
        if existing is None:
            discovered[canonical] = {"title": title, "discovery_source": source, "score": score}
        else:
            if title and not existing.get("title"):
                existing["title"] = title
            existing["score"] = max(existing.get("score", 0.0), score)

    map_hits = 0
    for root in MAP_ROOTS:
        try:
            urls = client.map(root, max_depth=map_depth, limit=map_limit)
            map_hits += len(urls)
            for u in urls:
                _add(u, source="tavily_map")
            logger.info("Tavily map %s -> %d urls", root, len(urls))
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Tavily map failed for %s: %s", root, exc)

    search_hits = 0
    for query in SEED_QUERIES:
        try:
            for result in client.search(query, max_results=per_query):
                search_hits += 1
                _add(result.url, source="tavily_search", title=result.title, score=result.score)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Tavily search failed for %r: %s", query, exc)
        time.sleep(0.2)

    # Classify and persist the URL map.
    by_category: Counter[str] = Counter()
    payload_urls = []
    for url, hint in discovered.items():
        classification = classify_umb_url(url, title=hint.get("title"))
        hint["page_type"] = classification.page_type
        hint["media_type"] = classification.media_type
        hint["content_type"] = classification.content_type
        hint["priority"] = classification.priority
        by_category[classification.page_type] += 1
        payload_urls.append({"url": url, **hint})

    payload_urls.sort(key=lambda item: item.get("priority", 0), reverse=True)
    URL_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    URL_MAP_PATH.write_text(
        json.dumps(
            {
                "generated_at": _timestamp(),
                "domain": client.strict_domain,
                "map_hits": map_hits,
                "search_hits": search_hits,
                "total_urls": len(payload_urls),
                "by_category": dict(by_category),
                "urls": payload_urls,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info(
        "Discovery complete: %d unique urls (map=%d, search=%d) -> %s",
        len(payload_urls),
        map_hits,
        search_hits,
        URL_MAP_PATH,
    )
    return discovered


def _load_url_map() -> dict[str, dict]:
    if not URL_MAP_PATH.exists():
        return {}
    data = json.loads(URL_MAP_PATH.read_text(encoding="utf-8"))
    return {item["url"]: item for item in data.get("urls", [])}


def ingest(
    *,
    limit: int,
    batch_size: int,
    rate_limit: float,
    refresh: bool,
    skip_pdf: bool,
) -> dict:
    """Extract content for discovered URLs via Tavily and index into the KB."""

    client = TavilyClient()
    client.ensure_configured()
    url_hints = _load_url_map()
    if not url_hints:
        raise SystemExit("No URL map found. Run the 'map' command first.")

    session_factory = get_session_local()
    delay = 1.0 / max(rate_limit, 0.1)

    # Order by classification priority so the most useful pages index first.
    ordered = sorted(url_hints.items(), key=lambda kv: kv[1].get("priority", 0), reverse=True)

    indexed = 0
    skipped = 0
    failed = 0
    empty = 0
    chunks_added = 0
    by_category: Counter[str] = Counter()

    pending: list[tuple[str, dict]] = []
    with session_factory() as db:
        for url, hint in ordered:
            if indexed + failed + empty >= limit:
                break
            if hint.get("media_type") == "document" and url.lower().endswith(".pdf") and skip_pdf:
                continue
            if hint.get("page_type") == "auth_or_system":
                skipped += 1
                continue
            if not refresh:
                existing = db.query(Source).filter(Source.url == url, Source.status == "indexed").first()
                if existing and source_has_chunks(db, url):
                    skipped += 1
                    continue
            pending.append((url, hint))

        for start in range(0, len(pending), batch_size):
            if indexed + failed + empty >= limit:
                break
            window = pending[start : start + batch_size]
            urls = [u for u, _ in window]
            try:
                extracted = client.extract(urls)
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Tavily extract failed for batch starting %s: %s", urls[0], exc)
                failed += len(urls)
                continue
            extracted_by_url = {r.url: r for r in extracted}
            for url, hint in window:
                result = extracted_by_url.get(url) or extracted_by_url.get(canonicalize_umb_url(url))
                if result is None:
                    failed += 1
                    continue
                cleaned = clean_umb_content(result.raw_content)
                if len(cleaned.split()) < 20:
                    empty += 1
                    continue
                title = hint.get("title") or filename_title(url)
                classification = classify_umb_url(url, title=title)
                metadata = {
                    "title": title,
                    "url": url,
                    "source_url": url,
                    "source_domain": url.split("/")[2] if "//" in url else None,
                    "source_category": classification.page_type,
                    "document_type": classification.media_type,
                    "content_type": classification.content_type,
                    "crawl_date": _timestamp(),
                    "published_date": None,
                    "discovery_source": hint.get("discovery_source", "tavily"),
                }
                try:
                    n = upsert_source_document(
                        db,
                        url,
                        cleaned,
                        title,
                        metadata,
                        http_status=200,
                        discovery_source=hint.get("discovery_source", "tavily"),
                        source_type=classification.content_type if classification.media_type == "document" else "html",
                        extraction_method="tavily_extract",
                        extraction_confidence=0.9,
                    )
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    logger.warning("Indexing failed for %s: %s", url, exc)
                    failed += 1
                    continue
                if n > 0:
                    indexed += 1
                    chunks_added += n
                    by_category[classification.page_type] += 1
                else:
                    empty += 1
            time.sleep(delay)

        report = {
            "generated_at": _timestamp(),
            "pages_indexed": indexed,
            "pages_skipped_already_indexed": skipped,
            "pages_failed": failed,
            "pages_empty": empty,
            "chunks_added": chunks_added,
            "indexed_by_category": dict(by_category),
            "indexed_sources_total": db.query(Source).filter(Source.status == "indexed").count(),
        }

    INGEST_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    INGEST_REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Ingest complete: %s", json.dumps(report, ensure_ascii=False))
    return report


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Tavily-first UMB knowledge-base ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    map_cmd = sub.add_parser("map", help="Discover the UMB URL map via Tavily map + search")
    map_cmd.add_argument("--per-query", type=int, default=10)
    map_cmd.add_argument("--map-limit", type=int, default=200)
    map_cmd.add_argument("--map-depth", type=int, default=2)
    map_cmd.add_argument("--confirm-authorized", action="store_true")

    ingest_cmd = sub.add_parser("ingest", help="Extract + index discovered URLs into the KB")
    ingest_cmd.add_argument("--limit", type=int, default=500)
    ingest_cmd.add_argument("--batch-size", type=int, default=15)
    ingest_cmd.add_argument("--rate-limit", type=float, default=1.0)
    ingest_cmd.add_argument("--refresh", action="store_true", help="Re-index URLs even if already indexed")
    ingest_cmd.add_argument("--skip-pdf", action="store_true")
    ingest_cmd.add_argument("--confirm-authorized", action="store_true")

    all_cmd = sub.add_parser("run-all", help="map then ingest")
    all_cmd.add_argument("--per-query", type=int, default=10)
    all_cmd.add_argument("--map-limit", type=int, default=200)
    all_cmd.add_argument("--map-depth", type=int, default=2)
    all_cmd.add_argument("--limit", type=int, default=500)
    all_cmd.add_argument("--batch-size", type=int, default=15)
    all_cmd.add_argument("--rate-limit", type=float, default=1.0)
    all_cmd.add_argument("--refresh", action="store_true")
    all_cmd.add_argument("--skip-pdf", action="store_true")
    all_cmd.add_argument("--confirm-authorized", action="store_true")

    args = parser.parse_args(argv)
    if not getattr(args, "confirm_authorized", False):
        raise SystemExit("Tavily discovery/extraction requires --confirm-authorized.")

    if args.command == "map":
        report = discover(per_query=args.per_query, map_limit=args.map_limit, map_depth=args.map_depth)
        print(json.dumps({"total_urls": len(report)}, indent=2, ensure_ascii=False))
    elif args.command == "ingest":
        report = ingest(
            limit=args.limit,
            batch_size=args.batch_size,
            rate_limit=args.rate_limit,
            refresh=args.refresh,
            skip_pdf=args.skip_pdf,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.command == "run-all":
        discover(per_query=args.per_query, map_limit=args.map_limit, map_depth=args.map_depth)
        report = ingest(
            limit=args.limit,
            batch_size=args.batch_size,
            rate_limit=args.rate_limit,
            refresh=args.refresh,
            skip_pdf=args.skip_pdf,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:  # pragma: no cover
        raise SystemExit("Unknown command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
