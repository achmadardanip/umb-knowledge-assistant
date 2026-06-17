from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.paths import project_path
from app.db.database import get_session_local
from app.db.models import Chunk, ChunkEmbedding, DiscoveredURL, Document, Source, utcnow
from app.discovery.scope_validator import validate_url_scope
from app.ingestion.embed_backfill import backfill_embeddings
from app.ingestion.firecrawl_client import FirecrawlAPIError, FirecrawlClient
from app.ingestion.firecrawl_pipeline import (
    _upsert_discovered_url,
    discover_firecrawl,
    run_firecrawl_index,
    scrape_pending_firecrawl,
)
from app.ingestion.index_state import metadata_for
from app.ingestion.pipeline import crawl_and_index_urls
from app.ingestion.umb_content import canonicalize_umb_url, classify_umb_url
from app.multimodal.multimodal_pipeline import run_all as run_multimodal
from app.web_search.tavily_client import TavilyClient


logger = logging.getLogger(__name__)
REPORT_DIR = project_path("reports")
DISCOVERY_URLS = project_path("data", "discovery", "urls_filtered.txt")
EXPECTED_AREAS = {
    "Profil Universitas": ("profil", "sejarah", "visi-misi", "rektor"),
    "Akademik": ("akademik", "academic"),
    "Fakultas": ("fakultas", "faculty"),
    "Biro Unit Universitas": ("biro-", "unit-", "direktorat"),
    "Lembaga Penjaminan Mutu": ("penjaminan-mutu", "lpm"),
    "Kabar Kampus": ("kabar-kampus", "berita"),
    "Satgas PPK UMB": ("satgas", "ppk"),
    "Keselamatan dan Kesehatan Kerja": ("k3", "k3lk", "keselamatan"),
    "PMB / Pendaftaran Mahasiswa Baru": ("pendaftaran", "pmb", "mahasiswa-baru"),
    "Kelas Internasional": ("kelas-internasional",),
    "Kelas Reguler 2": ("kelas-reguler-2", "reguler-2"),
    "Kelas Reguler": ("kelas-reguler",),
    "Kampus Meruya": ("meruya",),
    "Kampus Menteng": ("menteng",),
    "Kampus Warung Buncit": ("warung-buncit", "buncit"),
    "Perpustakaan": ("lib.mercubuana", "perpustakaan"),
    "BAA / Biro Pembelajaran": ("baa.mercubuana", "biro-pembelajaran"),
    "Repositori Daring": ("repository.mercubuana", "repository"),
    "Publikasi/Jurnal": ("publikasi.mercubuana", "journal", "jurnal"),
    "Fakultas Ilmu Komputer": ("fasilkom", "fakultas-ilmu-komputer"),
    "Struktur Organisasi Dekanat dan Program Studi": ("struktur-organisasi-dekanat", "struktural-dan-dosen"),
    "K3/K3LK reports": ("k3lk", "laporan-k3"),
    "PDF documents": (".pdf",),
    "images": (".jpg", ".jpeg", ".png", ".webp"),
    "videos": (".mp4", ".webm", ".mov", "youtube"),
}
GAP_FILL_QUERIES = (
    "profil Universitas Mercu Buana",
    "akademik kalender Universitas Mercu Buana",
    "pendaftaran mahasiswa baru Universitas Mercu Buana",
    "biaya kuliah Universitas Mercu Buana",
    "Fasilkom dekan program studi Universitas Mercu Buana",
    "lokasi kampus Meruya Menteng Warung Buncit Universitas Mercu Buana",
    "K3LK laporan Universitas Mercu Buana",
)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_authorized(confirm_authorized: bool) -> None:
    if not confirm_authorized:
        raise SystemExit("Real UMB ingestion requires --confirm-authorized.")


def _ensure_postgres(db: Session) -> None:
    dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "")
    if dialect != "postgresql":
        raise SystemExit(
            "UMB full refresh must target PostgreSQL + pgvector. Set LOCAL_POSTGRES_MODE=true with "
            "LOCAL_POSTGRES_URL (or DATABASE_URL) and set LOCAL_SQLITE_FALLBACK_ENABLED=false."
        )


def _load_seed_links(seed_json: str | Path) -> list[dict]:
    path = Path(seed_json).expanduser().resolve()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Unable to read seed JSON {path}: {exc}") from exc
    links = payload.get("links") if isinstance(payload, dict) else None
    if not isinstance(links, list):
        raise SystemExit("Seed JSON must be an object containing a 'links' array.")
    return [item for item in links if isinstance(item, dict)]


def _write_report(prefix: str, report: dict) -> tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    json_path = REPORT_DIR / f"{prefix}_{stamp}.json"
    md_path = REPORT_DIR / f"{prefix}_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    md_path.write_text(_report_markdown(report), encoding="utf-8")
    return json_path, md_path


def _report_markdown(report: dict) -> str:
    title = str(report.get("report_type") or "UMB ingestion report").replace("_", " ").title()
    lines = [f"# {title}", "", f"Generated: {report.get('generated_at', '')}", ""]
    for key, value in report.items():
        if key in {"report_type", "generated_at", "accepted_urls", "skipped_urls", "failed_urls"}:
            continue
        if isinstance(value, dict):
            lines.extend([f"## {key.replace('_', ' ').title()}", ""])
            for item_key, item_value in sorted(value.items()):
                lines.append(f"- **{item_key}**: {item_value}")
            lines.append("")
        elif isinstance(value, list):
            lines.extend([f"## {key.replace('_', ' ').title()}", ""])
            lines.extend(f"- {item}" for item in value[:200])
            lines.append("")
        else:
            lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
    for key in ("skipped_urls", "failed_urls"):
        values = report.get(key) or []
        if values:
            lines.extend([f"", f"## {key.replace('_', ' ').title()}", ""])
            for item in values[:200]:
                if isinstance(item, dict):
                    lines.append(f"- `{item.get('url', '')}`: {item.get('reason') or item.get('error') or 'unknown'}")
                else:
                    lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def _merge_discovery_file(urls: list[str]) -> None:
    existing: set[str] = set()
    if DISCOVERY_URLS.exists():
        existing.update(line.strip() for line in DISCOVERY_URLS.read_text(encoding="utf-8").splitlines() if line.strip())
    existing.update(urls)
    DISCOVERY_URLS.parent.mkdir(parents=True, exist_ok=True)
    DISCOVERY_URLS.write_text("\n".join(sorted(existing)) + "\n", encoding="utf-8")


def import_seed_json(
    *,
    seed_json: str | Path,
    source: str,
    confirm_authorized: bool,
    root_domain: str = "mercubuana.ac.id",
    require_postgres: bool = True,
    write_report: bool = True,
) -> dict:
    _ensure_authorized(confirm_authorized)
    links = _load_seed_links(seed_json)
    accepted: list[dict] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    duplicate_urls = 0
    by_domain: Counter[str] = Counter()
    by_content_type: Counter[str] = Counter()
    by_media_type: Counter[str] = Counter()
    by_page_type: Counter[str] = Counter()
    candidates: list[dict] = []
    for item in links:
        raw_url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip() or None
        description = str(item.get("description") or "").strip() or None
        if not raw_url:
            skipped.append({"url": "", "reason": "missing_url"})
            continue
        try:
            normalized = canonicalize_umb_url(raw_url, root_domain)
        except Exception:
            skipped.append({"url": raw_url, "reason": "invalid_url"})
            continue
        if normalized in seen:
            duplicate_urls += 1
            skipped.append({"url": normalized, "reason": "duplicate_url"})
            continue
        seen.add(normalized)
        decision = validate_url_scope(normalized, root_domain)
        classification = classify_umb_url(normalized, title=title, description=description)
        if not decision.is_allowed or classification.auth_or_system:
            reason = "auth_or_system" if classification.auth_or_system else decision.reason or "not_allowed"
            skipped.append({"url": normalized, "reason": reason})
            continue
        candidates.append(
            {
                "url": normalized,
                "title": title,
                "description": description,
                "classification": classification,
            }
        )

    with get_session_local()() as db:
        if require_postgres:
            _ensure_postgres(db)
        candidate_urls = [item["url"] for item in candidates]
        existing_by_url = {
            row.normalized_url: row
            for row in db.query(DiscoveredURL).filter(DiscoveredURL.normalized_url.in_(candidate_urls)).all()
        }
        for item in candidates:
            normalized = item["url"]
            title = item["title"]
            description = item["description"]
            classification = item["classification"]
            row = existing_by_url.get(normalized)
            if row is None:
                row = DiscoveredURL(url=normalized, normalized_url=normalized)
                db.add(row)
                existing_by_url[normalized] = row
            parsed = urlparse(normalized)
            host = (parsed.hostname or "").lower()
            row.hostname = host
            row.path = parsed.path or "/"
            row.discovery_source = row.discovery_source or f"seed_json:{source}"
            row.is_allowed = True
            row.rejection_reason = None
            row.meta = {
                **metadata_for(row),
                "title": title,
                "description": description,
                "seed_source": source,
                "seed_json": str(Path(seed_json).expanduser().resolve()),
                "canonical_url": normalized,
                "content_type": classification.content_type,
                "media_type": classification.media_type,
                "page_type": classification.page_type,
                "priority": classification.priority,
            }
            record = {
                "url": normalized,
                "hostname": host,
                "title": title,
                "content_type": classification.content_type,
                "media_type": classification.media_type,
                "page_type": classification.page_type,
                "priority": classification.priority,
            }
            accepted.append(record)
            by_domain[host] += 1
            by_content_type[classification.content_type] += 1
            by_media_type[classification.media_type] += 1
            by_page_type[classification.page_type] += 1
        db.commit()

    accepted.sort(key=lambda item: (-item["priority"], item["url"]))
    _merge_discovery_file([item["url"] for item in accepted])
    report = {
        "report_type": "umb_seed_import",
        "generated_at": utcnow().isoformat(),
        "seed_json": str(Path(seed_json).expanduser().resolve()),
        "source": source,
        "total_links_in_json": len(links),
        "accepted_official_links": len(accepted),
        "skipped_links": len(skipped),
        "duplicate_urls": duplicate_urls,
        "auth_login_urls_skipped": sum(1 for item in skipped if item["reason"] == "auth_or_system"),
        "count_by_domain": dict(by_domain),
        "count_by_content_type": dict(by_content_type),
        "count_by_media_type": dict(by_media_type),
        "count_by_page_type": dict(by_page_type),
        "high_priority_urls": [item["url"] for item in accepted if item["priority"] >= 100],
        "pdf_urls": [item["url"] for item in accepted if item["content_type"] == "pdf"],
        "image_urls": [item["url"] for item in accepted if item["media_type"] == "image"],
        "video_urls": [item["url"] for item in accepted if item["media_type"] == "video"],
        "accepted_urls": accepted,
        "skipped_urls": skipped,
    }
    if write_report:
        json_path, md_path = _write_report("umb_seed_import", report)
        report["report_json"] = str(json_path)
        report["report_markdown"] = str(md_path)
    return report


def tavily_gap_fill(
    *,
    domain: str,
    limit: int,
    confirm_authorized: bool,
    client: TavilyClient | None = None,
    firecrawl_client: FirecrawlClient | None = None,
    require_postgres: bool = True,
) -> dict:
    _ensure_authorized(confirm_authorized)
    client = client or TavilyClient()
    per_query = max(1, min(10, limit // max(1, len(GAP_FILL_QUERIES))))
    discovered = 0
    discovered_urls: list[str] = []
    warnings: list[str] = []
    with get_session_local()() as db:
        if require_postgres:
            _ensure_postgres(db)
        for query in GAP_FILL_QUERIES:
            try:
                results = client.search(query, max_results=per_query)
            except Exception as exc:
                warnings.append(f"{query}: {exc}")
                continue
            for result in results:
                _upsert_discovered_url(
                    db,
                    result.url,
                    discovery_source="tavily_gap_fill",
                    domain=domain,
                    title=result.title,
                    description=result.snippet,
                    extra={"search_query": query, "tavily_score": result.score, "requires_firecrawl": True},
                )
                discovered += 1
                discovered_urls.append(result.url)
        db.commit()
    scrape_report = scrape_pending_firecrawl(
        domain=domain,
        confirm_authorized=True,
        limit=max(1, min(limit, discovered or 1)),
        client=firecrawl_client,
        use_parse=True,
        require_postgres=require_postgres,
        candidate_urls=discovered_urls,
    )
    return {"discovered": discovered, "warnings": warnings, "firecrawl_ingest": scrape_report}


def _graph_counts(path: str) -> tuple[int, int]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    adjacency = payload.get("adj") or {}
    edges = sum(len(neighbors or {}) for neighbors in adjacency.values()) // 2
    return len(payload.get("entity_chunks") or {}), edges


def build_coverage_report(seed_report: dict | None = None, stage_reports: dict | None = None) -> dict:
    settings = get_settings()
    with get_session_local()() as db:
        discovered_rows = db.query(DiscoveredURL).all()
        sources = db.query(Source).all()
        chunks = db.query(Chunk).all()
        by_domain = Counter((row.hostname or "unknown") for row in discovered_rows if row.is_allowed)
        by_discovery = Counter((row.discovery_source or "unknown") for row in discovered_rows)
        by_page_type = Counter()
        by_content_type = Counter()
        by_media_type = Counter()
        for row in discovered_rows:
            meta = metadata_for(row)
            by_page_type[str(meta.get("page_type") or "unknown")] += 1
            by_content_type[str(meta.get("content_type") or "unknown")] += 1
            by_media_type[str(meta.get("media_type") or "unknown")] += 1
        failed = []
        skipped = []
        for row in discovered_rows:
            meta = metadata_for(row)
            status = meta.get("crawl_status")
            item = {"url": row.normalized_url or row.url, "reason": meta.get("last_error") or meta.get("terminal_reason") or row.rejection_reason}
            if status == "retryable_failed":
                failed.append(item)
            elif not row.is_allowed or status == "terminal":
                skipped.append(item)
        corpus = "\n".join(f"{source.url} {source.title or ''}" for source in sources).lower()
        area_coverage = {
            area: any(marker in corpus for marker in markers)
            for area, markers in EXPECTED_AREAS.items()
        }
        graph_nodes, graph_edges = _graph_counts(settings.graph_path)
        embeddings = db.query(func.count(ChunkEmbedding.id)).filter(ChunkEmbedding.profile == settings.embedding_profile).scalar() or 0
        report = {
            "report_type": "umb_crawl_coverage",
            "generated_at": utcnow().isoformat(),
            "total_urls_from_seed_json": int((seed_report or {}).get("total_links_in_json") or 0),
            "total_urls_discovered": len(discovered_rows),
            "total_urls_discovered_beyond_seed": max(
                0,
                len(discovered_rows) - int((seed_report or {}).get("accepted_official_links") or 0),
            ),
            "total_urls_crawled": sum(1 for row in discovered_rows if row.crawled_at is not None),
            "total_urls_indexed": sum(1 for row in discovered_rows if row.indexed),
            "total_sources_upserted": len(sources),
            "total_source_documents_upserted": db.query(func.count(Document.id)).scalar() or 0,
            "total_chunks": len(chunks),
            "total_embeddings": int(embeddings),
            "total_graph_nodes": graph_nodes,
            "total_graph_edges": graph_edges,
            "count_by_domain": dict(by_domain),
            "count_by_subdomain": dict(by_domain),
            "count_by_page_type": dict(by_page_type),
            "count_by_content_type": dict(by_content_type),
            "count_by_media_type": dict(by_media_type),
            "count_by_discovery_method": dict(by_discovery),
            "pdf_parsed_count": sum(1 for chunk in chunks if chunk.source_type == "pdf"),
            "image_metadata_indexed_count": sum(1 for chunk in chunks if chunk.source_type == "image"),
            "video_metadata_indexed_count": sum(1 for chunk in chunks if chunk.source_type == "video"),
            "low_content_pages": sum(1 for source in sources if source.status == "empty"),
            "failed_urls": failed,
            "skipped_urls": skipped,
            "area_coverage": area_coverage,
            "top_missing_expected_menu_areas": [area for area, covered in area_coverage.items() if not covered],
            "stage_reports": stage_reports or {},
            "multimodal_readiness": {
                "primary_embedding": "intfloat/multilingual-e5-small",
                "jina_optional_model": settings.jina_embedding_model,
                "jina_enabled": settings.multimodal_embedding_provider == "jina_v4",
                "qwen_vl_optional_model": settings.qwen_vl_model,
                "qwen_vl_enabled": settings.vision_provider == "qwen_vl",
                "text_retrieval_unchanged": True,
            },
        }
    json_path, md_path = _write_report("umb_crawl_coverage", report)
    report["report_json"] = str(json_path)
    report["report_markdown"] = str(md_path)
    return report


def _rebuild_graph() -> dict:
    settings = get_settings()
    from app.graph.graph_store import build_graph_from_db, save_graph

    with get_session_local()() as db:
        graph = build_graph_from_db(db)
    save_graph(graph, settings.graph_path)
    nodes, edges = _graph_counts(settings.graph_path)
    return {"path": settings.graph_path, "nodes": nodes, "edges": edges}


def full_refresh(args: argparse.Namespace) -> dict:
    _ensure_authorized(args.confirm_authorized)
    domain = args.domains[0]
    limit = max(1, args.limit)
    stage_reports: dict[str, object] = {}
    seed_report = import_seed_json(
        seed_json=args.seed_json,
        source=args.source,
        confirm_authorized=True,
        root_domain=domain,
        write_report=True,
    )
    stage_reports["seed_import"] = {
        "accepted": seed_report["accepted_official_links"],
        "skipped": seed_report["skipped_links"],
    }
    client = FirecrawlClient()

    if args.use_firecrawl_map or args.use_firecrawl_search or args.include_sitemap:
        try:
            stage_reports["firecrawl_discovery"] = discover_firecrawl(
                domain=domain,
                confirm_authorized=True,
                client=client,
                limit=limit,
            )
        except Exception as exc:
            logger.warning("Firecrawl discovery failed; continuing with seed URLs: %s", exc)
            stage_reports["firecrawl_discovery"] = {"error": str(exc)}
    if args.use_firecrawl_scrape or args.use_firecrawl_parse:
        try:
            stage_reports["firecrawl_seed_scrape"] = scrape_pending_firecrawl(
                domain=domain,
                confirm_authorized=True,
                limit=min(limit, max(1, seed_report["accepted_official_links"])),
                client=client,
                use_parse=args.use_firecrawl_parse,
                candidate_urls=[item["url"] for item in seed_report["accepted_urls"]],
            )
        except Exception as exc:
            logger.warning("Firecrawl seed scrape failed; direct fallback remains available: %s", exc)
            stage_reports["firecrawl_seed_scrape"] = {"error": str(exc)}
    if args.use_firecrawl_crawl:
        try:
            stage_reports["firecrawl_crawl"] = run_firecrawl_index(
                domain=domain,
                confirm_authorized=True,
                client=client,
                limit=limit,
                max_depth=args.max_depth,
                skip_existing=not args.refresh_existing,
            )
        except Exception as exc:
            logger.warning("Firecrawl crawl failed; continuing with indexed/scraped content: %s", exc)
            stage_reports["firecrawl_crawl"] = {"error": str(exc)}
    if args.use_tavily_gap_fill:
        try:
            stage_reports["tavily_gap_fill"] = tavily_gap_fill(
                domain=domain,
                limit=min(limit, 100),
                confirm_authorized=True,
                firecrawl_client=client,
            )
        except Exception as exc:
            logger.warning("Tavily gap fill failed; continuing without it: %s", exc)
            stage_reports["tavily_gap_fill"] = {"error": str(exc)}
    if args.direct_fetch_fallback:
        with get_session_local()() as db:
            fallback_urls = [
                row.normalized_url or row.url
                for row in db.query(DiscoveredURL)
                .filter(DiscoveredURL.is_allowed.is_(True), DiscoveredURL.indexed.is_(False))
                .limit(min(limit, 500))
                .all()
                if classify_umb_url(row.normalized_url or row.url).content_type == "html"
            ]
        if fallback_urls:
            stage_reports["direct_fetch_fallback"] = crawl_and_index_urls(
                fallback_urls,
                max_pages=len(fallback_urls),
                rate_limit=get_settings().crawler_rate_limit,
            )
    if args.include_multimodal:
        try:
            stage_reports["multimodal"] = run_multimodal(
                max_files=min(limit, get_settings().multimodal_max_files_per_run),
                urls=[item["url"] for item in seed_report["accepted_urls"]],
            )
        except Exception as exc:
            logger.warning("Multimodal ingestion failed; text ingestion remains usable: %s", exc)
            stage_reports["multimodal"] = {"error": str(exc)}
    if args.store_supabase:
        try:
            with get_session_local()() as db:
                stage_reports["embedding_backfill"] = {
                    "backfilled": backfill_embeddings(db, batch_size=64, limit=None, only_keyword_only=False)
                }
        except Exception as exc:
            logger.warning("Embedding backfill failed; keyword indexing remains available: %s", exc)
            stage_reports["embedding_backfill"] = {"error": str(exc)}
    if args.update_graph:
        try:
            stage_reports["graph"] = _rebuild_graph()
        except Exception as exc:
            logger.warning("Graph rebuild failed; base retrieval remains available: %s", exc)
            stage_reports["graph"] = {"error": str(exc)}
    return build_coverage_report(seed_report, stage_reports)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Official UMB seed import and full Firecrawl refresh")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("import-seeds")
    seed.add_argument("--seed-json", required=True)
    seed.add_argument("--source", default="official_umb")
    seed.add_argument("--domain", default="mercubuana.ac.id")
    seed.add_argument("--confirm-authorized", action="store_true")

    refresh = sub.add_parser("full-refresh")
    refresh.add_argument("--confirm-authorized", action="store_true")
    refresh.add_argument("--seed-json", required=True)
    refresh.add_argument("--source", default="official_umb")
    refresh.add_argument("--domains", nargs="+", default=["mercubuana.ac.id"])
    refresh.add_argument("--include-subdomains", action="store_true")
    refresh.add_argument("--include-sitemap", action="store_true")
    refresh.add_argument("--use-firecrawl-search", action="store_true")
    refresh.add_argument("--use-firecrawl-map", action="store_true")
    refresh.add_argument("--use-firecrawl-crawl", action="store_true")
    refresh.add_argument("--use-firecrawl-scrape", action="store_true")
    refresh.add_argument("--use-firecrawl-parse", action="store_true")
    refresh.add_argument("--use-tavily-gap-fill", action="store_true")
    refresh.add_argument("--include-multimodal", action="store_true")
    refresh.add_argument("--parse-pdf", action="store_true")
    refresh.add_argument("--index-images-metadata", action="store_true")
    refresh.add_argument("--index-video-metadata", action="store_true")
    refresh.add_argument("--store-supabase", action="store_true")
    refresh.add_argument("--update-graph", action="store_true")
    refresh.add_argument("--direct-fetch-fallback", action=argparse.BooleanOptionalAction, default=True)
    refresh.add_argument("--refresh-existing", action="store_true")
    refresh.add_argument("--max-depth", type=int, default=4)
    refresh.add_argument("--limit", type=int, default=10000)

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--domain", default="mercubuana.ac.id")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import-seeds":
            report = import_seed_json(
                seed_json=args.seed_json,
                source=args.source,
                confirm_authorized=args.confirm_authorized,
                root_domain=args.domain,
            )
        elif args.command == "full-refresh":
            report = full_refresh(args)
        elif args.command == "coverage":
            report = build_coverage_report()
        else:
            raise SystemExit("Unknown command")
    except FirecrawlAPIError as exc:
        logger.error("Firecrawl stage failed: %s", exc)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
