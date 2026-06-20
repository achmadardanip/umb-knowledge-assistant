# Freshness Pipeline

## Purpose
Let users know where information came from, when it was retrieved, and whether it may be
outdated — without weakening retrieval. Stale sources are flagged + down-weighted, never hidden.

## Flow
```
ingestion/crawl → sources.fetched_at (crawl_date), content_hash, first_seen_date, last_verified_date
retrieval response → enrich_sources_with_freshness(db, sources):
    crawl_date, freshness_days, freshness_tier (green ≤30 / yellow 31-180 / red >180),
    freshness_label ("Updated N days ago"), authority_tier
  → apply_freshness_confidence: multiplier (1.0 / 0.97 / 0.85) + stale warning (post-retrieval)
UI → SourcesPanel renders a coloured freshness badge in the source drawer
```
The penalty adjusts ranking **confidence** only (not membership/order/citations), so it cannot
regress official_top/citation_failure. On the all-fresh KB the multiplier is 1.0 (no-op).

## Key files
- `app/rag/freshness.py` — `enrich_sources_with_freshness`, tiers, labels, authority_tier.
- `app/rag/freshness_scoring.py` — `freshness_multiplier`, `apply_freshness_confidence`.
- `app/db/migrate_freshness.py` — additive freshness columns + backfill.
- `frontend/app/components/SourcesPanel.tsx` — badge + drawer.

## APIs
`GET /system/freshness`; freshness fields are embedded in each chat source.

## Benchmarks
- `stale_content_audit` → freshness_audit.json: 100% sources carry a crawl date, 0 stale.
- `freshness_ranking_validation` → 0 penalised on the fresh KB (0 regression).

## Risks
- Everything currently reads "fresh" (KB rebuilt recently) — thresholds correct but untriggered until content ages.

## Future improvements
- Bump `last_verified_date` when the crawler re-verifies unchanged pages.
