"""
P2 — Coverage-expansion DRY RUN (projection only).

Pipeline:  Tavily Map → URL Discovery → URL Classification → Authority Scoring →
Coverage Projection → Coverage Report.

DRY RUN means: **no live Tavily calls, no DB writes, no embeddings, no ingestion.**
It projects the discovery/ingest footprint for the high-value official subdomains so
the cost (Tavily credits, storage, Postgres growth) can be approved BEFORE any spend.
When a real Tavily-Map URL list is supplied (``--urls-file``, gathered after approval),
the same code classifies the real URLs instead of projecting.

Run:  PYTHONPATH=. python -m app.discovery.coverage_expansion_dryrun
→ writes reports/coverage_expansion_report.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from app.discovery.scope_validator import validate_url_scope
from app.trust.authority import host_authority

# Below this host authority a URL is treated as archive/repository and dropped
# (Phase-6A: "no repository, no archive URLs").
MIN_HOST_AUTHORITY = 0.4

ROOT_DOMAIN = "mercubuana.ac.id"

# Target ACCEPTED knowledge pages per priority subdomain (Phase-6A goals).
PRIORITY_DOMAINS: dict[str, int] = {
    "pmb.mercubuana.ac.id": 500,
    "pendaftaran.mercubuana.ac.id": 500,
    "sia.mercubuana.ac.id": 300,
    "sso.mercubuana.ac.id": 100,
    "bti.mercubuana.ac.id": 300,
    "support.mercubuana.ac.id": 200,
    "baa.mercubuana.ac.id": 300,
}

# Projection constants grounded in the current KB.
AVG_CHUNKS_PER_PAGE = 4
CHUNK_TEXT_BYTES = 900
EMBEDDING_BYTES = 384 * 4            # float32 384-dim e5-small vector = 1536 B
METADATA_BYTES = 523                 # measured post-prune average
INDEX_OVERHEAD = 1.3                 # HNSW + pg_trgm index amplification
ACCEPTANCE_RATE = 0.7                # projected official-subdomain accept rate
MAP_LIMIT = 200                      # Tavily map URLs per call
EXTRACT_BATCH = 20                   # Tavily extract URLs per call


def _mb(num_bytes: float) -> float:
    return round(num_bytes / (1024 * 1024), 2)


def classify_urls(urls: list[str], root_domain: str = ROOT_DOMAIN) -> dict:
    """Run the real scope filter + authority score over discovered URLs."""
    accepted: list[str] = []
    rejected: dict[str, int] = {}

    def _reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for url in urls:
        decision = validate_url_scope(url, root_domain)
        if not decision.is_allowed:
            _reject(decision.reason or "rejected")
            continue
        host = urlparse(url).hostname or ""
        if host_authority(host, root_domain) < MIN_HOST_AUTHORITY:
            _reject("low_authority_archive")  # repository / journal / proceedings
            continue
        accepted.append(url)
    return {"accepted": accepted, "rejected": rejected}


def _projection(accepted: int, discovered: int) -> dict:
    per_chunk = CHUNK_TEXT_BYTES + EMBEDDING_BYTES + METADATA_BYTES
    chunks = accepted * AVG_CHUNKS_PER_PAGE
    storage = chunks * per_chunk
    return {
        "pages_discovered": discovered,
        "pages_accepted": accepted,
        "pages_rejected": max(0, discovered - accepted),
        "projected_chunks": chunks,
        "projected_storage_mb": _mb(storage),
        "projected_postgres_growth_mb": _mb(storage * INDEX_OVERHEAD),
        "projected_tavily_map_calls": math.ceil(discovered / MAP_LIMIT) if discovered else 0,
        "projected_tavily_extract_calls": math.ceil(accepted / EXTRACT_BATCH) if accepted else 0,
    }


def project_domain(domain: str, target_pages: int, discovered_urls: list[str] | None = None) -> dict:
    if discovered_urls is not None:
        result = classify_urls(discovered_urls, ROOT_DOMAIN)
        accepted = len(result["accepted"])
        discovered = len(discovered_urls)
        rejected_reasons = result["rejected"]
    else:
        accepted = target_pages
        discovered = round(target_pages / ACCEPTANCE_RATE)
        rejected_reasons = {"projected_off_scope": discovered - accepted}
    proj = _projection(accepted, discovered)
    proj.update({
        "domain": domain,
        "target_pages": target_pages,
        "authority": round(host_authority(domain, ROOT_DOMAIN), 3),
        "rejected_reasons": rejected_reasons,
        "mode": "classified" if discovered_urls is not None else "projected",
    })
    return proj


def build_report(domains: dict[str, int] | None = None, discovered: dict[str, list[str]] | None = None) -> dict:
    domains = domains or PRIORITY_DOMAINS
    per_domain = [
        project_domain(d, t, (discovered or {}).get(d)) for d, t in domains.items()
    ]
    totals = {
        "pages_discovered": sum(p["pages_discovered"] for p in per_domain),
        "pages_accepted": sum(p["pages_accepted"] for p in per_domain),
        "pages_rejected": sum(p["pages_rejected"] for p in per_domain),
        "projected_chunks": sum(p["projected_chunks"] for p in per_domain),
        "projected_storage_mb": round(sum(p["projected_storage_mb"] for p in per_domain), 2),
        "projected_postgres_growth_mb": round(sum(p["projected_postgres_growth_mb"] for p in per_domain), 2),
        "projected_tavily_map_calls": sum(p["projected_tavily_map_calls"] for p in per_domain),
        "projected_tavily_extract_calls": sum(p["projected_tavily_extract_calls"] for p in per_domain),
    }
    return {
        "dry_run": True,
        "note": "Projection only — no Tavily calls, no DB writes, no embeddings, no ingestion.",
        "root_domain": ROOT_DOMAIN,
        "assumptions": {
            "avg_chunks_per_page": AVG_CHUNKS_PER_PAGE,
            "bytes_per_chunk": CHUNK_TEXT_BYTES + EMBEDDING_BYTES + METADATA_BYTES,
            "acceptance_rate": ACCEPTANCE_RATE,
            "index_overhead": INDEX_OVERHEAD,
        },
        "per_domain": per_domain,
        "totals": totals,
        "filters_enforced": [
            "official subdomains only (is_allowed_host)",
            "no login/sensitive paths (sensitive_or_private_path)",
            "no stateful/transactional URLs",
            "no non-knowledge assets",
            "archive/repository hosts down-weighted by host_authority",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="P2 coverage-expansion dry run (projection)")
    ap.add_argument("--urls-file", default=None,
                    help="optional JSON {domain: [urls]} from a real Tavily Map (post-approval)")
    args = ap.parse_args()

    discovered = None
    if args.urls_file:
        discovered = json.loads(Path(args.urls_file).read_text(encoding="utf-8"))

    report = build_report(discovered=discovered)
    out = Path(__file__).resolve().parents[3] / "reports" / "coverage_expansion_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    t = report["totals"]
    print(f"DRY RUN ({'classified' if discovered else 'projected'}) — {len(report['per_domain'])} priority domains")
    print(f"  pages: {t['pages_accepted']} accepted / {t['pages_discovered']} discovered / {t['pages_rejected']} rejected")
    print(f"  chunks: {t['projected_chunks']}  storage: {t['projected_storage_mb']} MB  PG growth: {t['projected_postgres_growth_mb']} MB")
    print(f"  Tavily: {t['projected_tavily_map_calls']} map + {t['projected_tavily_extract_calls']} extract calls")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
