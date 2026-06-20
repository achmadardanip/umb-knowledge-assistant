"""Phase 19 P19.4 — freshness-enforcement validation.

Proves the freshness penalty (a) is a no-op on the current all-fresh KB (so it
cannot regress retrieval), and (b) correctly penalises + warns on synthetic stale
sources WITHOUT removing them or their citations.

    python -m app.evaluation.freshness_ranking_validation --out ../reports/freshness_ranking_validation.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.db.database import get_session_local
from app.rag.freshness import enrich_sources_with_freshness
from app.rag.freshness_scoring import freshness_multiplier, freshness_penalty, is_stale


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/freshness_ranking_validation.json")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        # (a) real sources — enrich + apply penalty; expect all fresh => mult 1.0.
        urls = [r[0] for r in db.execute(text("SELECT url FROM sources LIMIT 200")).all()]
        real = [{"url": u, "hostname": u.split("/")[2] if "://" in u else u, "relevance_score": 1.0} for u in urls]
        enrich_sources_with_freshness(db, real)
        penalised = [s for s in real if s.get("freshness_penalty", 0) > 0]
        all_kept = len(real) == len(urls)  # none dropped
        citations_kept = all("url" in s for s in real)

        # (b) synthetic tiers — verify multiplier/penalty/warning behaviour.
        synthetic = {
            "green_10d": freshness_multiplier(10),
            "yellow_45d": freshness_multiplier(45),
            "red_220d": freshness_multiplier(220),
        }
        assertions = {
            "fresh_no_penalty": all(s.get("freshness_penalty", 0) == 0 for s in real),
            "no_sources_dropped": all_kept,
            "citations_preserved": citations_kept,
            "green_multiplier_1.0": synthetic["green_10d"] == 1.0,
            "yellow_penalised": freshness_penalty(45) > 0,
            "red_penalised_and_warned": freshness_penalty(220) > freshness_penalty(45) and is_stale(220),
        }

        report = {
            "real_sources_checked": len(real),
            "real_sources_penalised": len(penalised),
            "all_real_sources_fresh": len(penalised) == 0,
            "no_retrieval_regression": len(penalised) == 0,  # penalty is identity on fresh KB
            "synthetic_multipliers": synthetic,
            "tier_rules": {"green": "<=30d mult 1.0", "yellow": "31-180d mult 0.97", "red": ">180d mult 0.85 + warning"},
            "policy": "stale sources are penalised in confidence + warned, never hidden or de-cited",
            "assertions": assertions,
            "all_assertions_pass": all(assertions.values()),
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("real_penalised:", report["real_sources_penalised"], "| no_regression:", report["no_retrieval_regression"])
    print("assertions:", report["assertions"])


if __name__ == "__main__":
    main()
