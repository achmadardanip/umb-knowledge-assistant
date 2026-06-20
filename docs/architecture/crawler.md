# Crawl Pipeline (Incremental)

## Purpose
Keep the KB current without full re-crawls: re-ingest only pages whose content actually
changed, on a daily/weekly/monthly cadence.

## Flow
```
scheduler.tick → due_urls(frequency) → for each url:
   fetch (HttpFetcher: conditional GET / If-Modified-Since)  → content_hash
   detect_changed_content(url, new_hash, last_modified):
       new | hash_changed | last_modified_changed → re-ingest (crawl_and_index_urls)
                                                     + bump source fetched_at/last_verified
       unchanged                                   → record_crawl(skipped) + bump last_verified
   record_crawl(...) updates crawl_registry (crash-safe, per-URL commit)
```

## Key files
- `app/crawl/incremental.py` — `detect_changed_content`, `record_crawl`, `due_urls`, `registry_status`.
- `app/crawl/crawler_worker.py` — `run_worker`, `process_url`, `HttpFetcher`/`VerifyFetcher`.
- `app/crawl/crawler_scheduler.py` — tiers (daily/weekly/monthly), `tick`, `run_daemon`.
- `app/db/migrate_freshness.py` — seeds `crawl_registry` from `sources`.

## APIs
`GET /crawl/status`, `GET /crawl/recent`, `GET /system/crawl`.

## Benchmarks
- `crawler_runtime_validation` — 285/285 unchanged skipped, 15/15 changes detected, 0 duplicate growth.
- `crawl_efficiency` — 100% skip on unchanged, 100% provenance retained.

## Risks
- The scheduler runs on demand (`--tick`) / as `--daemon`; **no OS cron wired yet** → not autonomous in prod.
- Live network fetch path (`HttpFetcher` + `crawl_and_index_urls`) is implemented but unexercised in CI.

## Future improvements
- systemd-timer/cron activation; alerting on `crawl_status='failed'`; ETag support.
