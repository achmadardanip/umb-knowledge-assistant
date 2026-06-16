"""
Phase-7 STEP 3 — official-domain discovery via Tavily Map (DISCOVERY ONLY).

For each high-value subdomain: Tavily Map -> URL discovery -> scope validation ->
authority classification. Makes REAL Tavily Map calls (authorized discovery tool) but
performs NO extraction, NO embedding, NO DB writes. Output is the real, validated URL
inventory needed to scope/approve the crawl + ingestion step.

Run:  PYTHONPATH=. python -m app.discovery.domain_discovery [--limit 300] [--max-depth 2]
→ writes reports/domain_discovery_report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.discovery.coverage_expansion_dryrun import PRIORITY_DOMAINS, classify_urls
from app.web_search.tavily_client import TavilyClient, WebSearchConfigurationError


def discover_domain(client: TavilyClient, domain: str, *, max_depth: int, limit: int) -> dict:
    seed = f"https://{domain}/"
    try:
        urls = client.map(seed, max_depth=max_depth, limit=limit)
        error = None
    except Exception as exc:
        urls, error = [], str(exc)
    # ``map`` already scope-validates; re-run the full classifier for authority + reasons.
    classified = classify_urls(urls)
    return {
        "domain": domain,
        "seed": seed,
        "discovered": len(urls),
        "accepted": len(classified["accepted"]),
        "rejected": sum(classified["rejected"].values()),
        "rejected_reasons": classified["rejected"],
        "accepted_urls": classified["accepted"],
        "error": error,
    }


def run_discovery(domains=None, *, max_depth: int = 2, limit: int = 300) -> dict:
    client = TavilyClient()
    client.ensure_configured()
    domains = domains or list(PRIORITY_DOMAINS)
    per_domain = [discover_domain(client, d, max_depth=max_depth, limit=limit) for d in domains]
    totals = {
        "discovered": sum(d["discovered"] for d in per_domain),
        "accepted": sum(d["accepted"] for d in per_domain),
        "rejected": sum(d["rejected"] for d in per_domain),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "discovery_only": True,
        "note": "Tavily Map only — no extraction, no embedding, no DB writes.",
        "max_depth": max_depth,
        "limit_per_domain": limit,
        "per_domain": per_domain,
        "totals": totals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase-7 official-domain discovery (Tavily Map only)")
    ap.add_argument("--limit", type=int, default=300, help="max URLs mapped per domain")
    ap.add_argument("--max-depth", type=int, default=2)
    args = ap.parse_args()

    try:
        report = run_discovery(max_depth=args.max_depth, limit=args.limit)
    except WebSearchConfigurationError as exc:
        print(f"Tavily not configured: {exc}")
        return 2

    out = Path(__file__).resolve().parents[3] / "reports" / "domain_discovery_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    t = report["totals"]
    print(f"discovery: {t['accepted']} accepted / {t['discovered']} discovered / {t['rejected']} rejected")
    for d in report["per_domain"]:
        tag = f" ERROR={d['error']}" if d["error"] else ""
        print(f"  {d['domain']:32s} disc={d['discovered']:4d} acc={d['accepted']:4d} rej={d['rejected']:4d}{tag}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
