"""Phase 19 P19.1 — incremental crawler *scheduler*.

Decides which frequency tier is due and drives the worker. Tiers:

  * daily   — critical sources (pendaftaran / baa / mercubuana root / pmb)
  * weekly  — normal sources
  * monthly — archive sources (repository / journals / proceedings)

``tick()`` runs every tier whose cadence has elapsed (idempotent — the worker
skips URLs that aren't actually due). ``run_daemon`` loops with a sleep; in
production prefer an OS cron / systemd-timer calling ``--tick`` so the process
stays crash-safe and resumable.

    python -m app.crawl.crawler_scheduler --reclassify           # tag archive=monthly
    python -m app.crawl.crawler_scheduler --tick                 # one scheduled pass (live)
    python -m app.crawl.crawler_scheduler --tick --verify        # dry validation pass (no network)
"""

from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy import text

from app.crawl.crawler_worker import HttpFetcher, VerifyFetcher, run_worker
from app.db.database import get_session_local

logger = logging.getLogger("umb.crawler.scheduler")

# Archive hosts get the slowest cadence (rarely change, low answer-value).
_ARCHIVE_HOSTS = ("repository.", "publikasi.", "journal.", "jurnal.", "ejournal.", "digilib.")

TIERS = ("daily", "weekly", "monthly")


def reclassify(db) -> dict:
    """Tag archive hosts as monthly so they're not crawled on the weekly cadence."""
    clause = " OR ".join(f"hostname ILIKE '{h}%'" for h in _ARCHIVE_HOSTS)
    n = db.execute(text(f"UPDATE crawl_registry SET crawl_frequency='monthly' WHERE {clause}")).rowcount
    db.commit()
    return {"reclassified_to_monthly": n}


def tick(db, *, verify: bool = False, mutate: set[str] | None = None, limit: int = 200, apply_reingest: bool | None = None) -> dict:
    """Run one scheduled pass across all tiers. In verify mode no network/reingest
    happens (deterministic validation)."""
    fetcher = VerifyFetcher(mutate=mutate) if verify else HttpFetcher()
    do_reingest = (not verify) if apply_reingest is None else apply_reingest
    results = {}
    for tier in TIERS:
        results[tier] = run_worker(db, frequency=tier, fetcher=fetcher, limit=limit, apply_reingest=do_reingest)
    return {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tiers": results}


def run_daemon(interval_sec: int = 3600) -> None:  # pragma: no cover - long-running
    SessionLocal = get_session_local()
    while True:
        with SessionLocal() as db:
            try:
                logger.info("scheduler tick: %s", tick(db))
            except Exception as e:
                logger.exception("scheduler tick failed: %s", e)
        time.sleep(interval_sec)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--reclassify", action="store_true")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--verify", action="store_true", help="no-network validation pass")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=3600)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()

    if args.daemon:
        run_daemon(args.interval)
        return

    db = get_session_local()()
    try:
        if args.reclassify:
            print(reclassify(db))
        if args.tick:
            res = tick(db, verify=args.verify, limit=args.limit)
            for tier, r in res["tiers"].items():
                print(f"  {tier:8s} due={r['due']:>4} processed={r['processed']:>4} counts={r['counts']} "
                      f"dup_growth={r['duplicate_chunk_growth']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
