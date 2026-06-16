"""
Phase-7 broadened coverage ingestion driver (official sources only).

Gathers official ``*.mercubuana.ac.id`` URLs via Tavily Map (priority subdomains) +
Tavily Search across high-value topics (surfaces pages + PDFs the login-gated portals
don't expose), then ingests HTML + PDF into the configured KB (LOCAL_POSTGRES_MODE
recommended) and writes a before/after coverage growth report.

Run:  LOCAL_POSTGRES_MODE=true LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb \
      PYTHONPATH=. python -m app.ingestion.phase7_coverage_ingest [--max-urls 250]
→ writes reports/coverage_growth_report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func

from app.db.models import Chunk, Source
from app.discovery.coverage_expansion_dryrun import PRIORITY_DOMAINS
from app.discovery.scope_validator import validate_url_scope
from app.ingestion.official_ingest import ROOT_DOMAIN, ingest_urls
from app.web_search.tavily_client import TavilyClient

# High-value topical queries (Tavily scopes each to site:mercubuana.ac.id).
SEARCH_QUERIES = [
    "cara pendaftaran mahasiswa baru", "syarat pendaftaran", "jalur pendaftaran", "biaya kuliah",
    "informasi beasiswa", "panduan beasiswa", "panduan sia", "panduan sso", "cara login sia",
    "reset password sso", "panduan krs", "panduan khs", "kalender akademik", "cuti akademik",
    "panduan wisuda", "yudisium", "registrasi mahasiswa", "panduan lms", "email mahasiswa",
    "struktur organisasi fakultas", "akreditasi program studi", "layanan perpustakaan",
    "legalisir ijazah", "panduan kemahasiswaan", "pedoman akademik",
]


def gather_urls(client: TavilyClient, *, map_depth: int = 2, map_limit: int = 200, max_urls: int = 250) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []

    def _add(u: str) -> None:
        if u and u not in seen and validate_url_scope(u, ROOT_DOMAIN).is_allowed:
            seen.add(u)
            urls.append(u)

    # 1) Map the mappable priority subdomains.
    for domain in PRIORITY_DOMAINS:
        try:
            for u in client.map(f"https://{domain}/", max_depth=map_depth, limit=map_limit):
                _add(u)
        except Exception:
            pass
        if len(urls) >= max_urls:
            return urls[:max_urls]
    # 2) Search high-value topics across the whole official domain (surfaces PDFs too).
    for q in SEARCH_QUERIES:
        try:
            for r in client.search(q, max_results=10):
                _add(r.url)
        except Exception:
            pass
        if len(urls) >= max_urls:
            break
    return urls[:max_urls]


def _counts(db) -> dict:
    return {
        "sources": db.query(func.count(Source.id)).scalar() or 0,
        "chunks": db.query(func.count(Chunk.id)).scalar() or 0,
        "pdf_chunks": db.query(func.count(Chunk.id)).filter(Chunk.source_type == "pdf").scalar() or 0,
    }


def run(*, max_urls: int = 250) -> dict:
    from app.db.database import get_session_local

    client = TavilyClient()
    client.ensure_configured()
    SessionLocal = get_session_local()

    with SessionLocal() as db:
        before = _counts(db)
    urls = gather_urls(client, max_urls=max_urls)
    with SessionLocal() as db:
        stats = ingest_urls(db, urls, client=client)
    with SessionLocal() as db:
        after = _counts(db)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "urls_gathered": len(urls),
        "ingestion": stats,
        "before": before,
        "after": after,
        "growth": {k: after[k] - before[k] for k in before},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-7 broadened official coverage ingestion")
    ap.add_argument("--max-urls", type=int, default=250)
    args = ap.parse_args()

    report = run(max_urls=args.max_urls)
    out = Path(__file__).resolve().parents[3] / "reports" / "coverage_growth_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    i = report["ingestion"]
    print(f"gathered {report['urls_gathered']} urls | ingested {i['ingested']} "
          f"({i['by_type']['html']} html / {i['by_type']['pdf']} pdf), skipped {i['skipped']}, failed {i['failed']}")
    print(f"chunks: {report['before']['chunks']} -> {report['after']['chunks']} (+{report['growth']['chunks']})")
    print(f"sources: {report['before']['sources']} -> {report['after']['sources']} (+{report['growth']['sources']})")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
