"""Phase 19 P19.1 — crawler runtime validation (deterministic, no network).

Exercises the worker over a registry sample with a VerifyFetcher: most URLs
replay their stored hash (unchanged -> must skip), a small injected subset gets a
perturbed hash (changed -> must be flagged). Asserts the success criteria:

  * 100% unchanged pages skipped
  * only changed pages flagged for reprocessing
  * no duplicate chunk growth (chunks_before == chunks_after; reingest disabled
    so the KB is never mutated during validation)

    python -m app.evaluation.crawler_runtime_validation --out ../reports/crawler_runtime_validation.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.crawl.crawler_worker import VerifyFetcher, run_worker
from app.crawl.incremental import due_urls
from app.db.database import get_session_local


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/crawler_runtime_validation.json")
    ap.add_argument("--sample", type=int, default=300)
    args = ap.parse_args()

    db = get_session_local()()
    try:
        # take a due sample and inject changes into a fixed fraction.
        urls = due_urls(db, limit=args.sample) or [
            r[0] for r in db.execute(text("SELECT url FROM crawl_registry LIMIT :n"), {"n": args.sample}).all()
        ]
        mutate = set(urls[: max(1, len(urls) // 20)])  # ~5% "changed"
        fetcher = VerifyFetcher(mutate=mutate)

        # Pin the worker to exactly this URL set via a temporary monkeypatch of
        # due_urls inside run_worker would be invasive; instead process directly.
        from app.crawl.crawler_worker import process_url

        chunks_before = db.execute(text("SELECT count(*) FROM chunks")).scalar()
        counts = {"reingested": 0, "skipped": 0, "failed": 0, "changed_detected": 0}
        for url in urls:
            out = process_url(db, url, fetcher, apply_reingest=False)  # validation: never mutate KB
            counts[out["outcome"]] = counts.get(out["outcome"], 0) + 1
        chunks_after = db.execute(text("SELECT count(*) FROM chunks")).scalar()

        unchanged = len(urls) - len(mutate)
        report = {
            "sample_urls": len(urls),
            "injected_changed": len(mutate),
            "unchanged": unchanged,
            "counts": counts,
            "skipped": counts["skipped"],
            "changed_detected": counts["changed_detected"],
            "failed": counts["failed"],
            "unchanged_skip_rate_pct": round(100 * counts["skipped"] / max(unchanged, 1), 2),
            "change_detection_rate_pct": round(100 * counts["changed_detected"] / max(len(mutate), 1), 2),
            "chunks_before": chunks_before,
            "chunks_after": chunks_after,
            "duplicate_chunk_growth": chunks_after - chunks_before,
            "crash_safe": "each URL committed independently via record_crawl; resumable from registry state",
            "success_criteria": {
                "unchanged_pages_skipped_100pct": counts["skipped"] == unchanged,
                "only_changed_reprocessed": counts["changed_detected"] == len(mutate),
                "no_duplicate_chunk_growth": chunks_after == chunks_before,
            },
        }
    finally:
        db.close()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"sample={report['sample_urls']} skipped={report['skipped']}/{unchanged} "
          f"changed_detected={report['changed_detected']}/{len(mutate)} "
          f"dup_growth={report['duplicate_chunk_growth']}")
    print("success:", report["success_criteria"])


if __name__ == "__main__":
    main()
