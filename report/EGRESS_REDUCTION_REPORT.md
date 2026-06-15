# v3 P5 — Supabase Egress Reduction Report

**Reported overage:** 16.08 GB used of 5.5 GB limit (monthly egress/bandwidth).

## Audit (largest tables + payload sizes)

| Table | Total size | Notes |
|---|--:|---|
| `chunks` | **189.8 MB** | metadata is TOASTed and huge (see below) |
| `discovered_urls` | 94.0 MB | crawl bookkeeping — not on the read hot path |
| `documents` | 52.4 MB | raw text — not read per chat |
| `chunk_embeddings` | 48.6 MB | 384-d vectors (read via pgvector ORDER BY only) |
| `sources` | 5.5 MB | |

**Root cause of egress** — `chunks.metadata` averages **13,410 chars/row (max 82,070)**, *larger than the chunk text itself (avg 7,239)*. It is dominated by data the retriever never reads:

| metadata key | avg size | |
|---|--:|---|
| `links` | **30,837 chars** | every link on the page (mostly repository archive links) |
| `DC.description` / `eprints.abstract` | up to 39 KB | full thesis abstracts, duplicated |
| `images`, `DC.*`, `eprints.*`, `schema_org`, `tables`, `headings` | — | EPrints/crawler junk |

Every retrieval loaded ~200 candidate rows (keyword) + dense candidates, each pulling ~20 KB (text + bloated metadata + legacy 1.5 KB vector) → **~4 MB per query**, repeated across thousands of queries = the egress overage.

## Fixes implemented (this PR)

1. **Metadata allowlist at ingest** (`app/ingestion/metadata_pruning.py`, wired into `pipeline.upsert_source_document`): new chunks store only the ~20 small keys the retriever reads (~13 KB → <0.5 KB, ≈96% reduction). *Non-destructive; applies going forward.*
2. **Shared cache layer** (`app/core/cache.py`) — in-process TTL+LRU, **Redis** when `REDIS_URL` is set. Caches, in order, **FAQ → Entity → Retrieval**:
   - FAQ active rows cached (was read every chat).
   - Entity lookups cached per query.
   - **Retrieval results cached per query** — verified: a repeated query returns in **0.000 s with zero Supabase reads** (was ~28 s / ~4 MB). This is the dominant production saver (popular questions repeat).
   - Graph layers were already file-cached (mtime).
3. **Projection** — `defer(Chunk.embedding)` on both the keyword and dense candidate joins (the legacy 1.5 KB vector, present in 981 chunks, is never used by retrieval). Combined with the keyword-path defer from v2, retrieval no longer transfers vectors.

## One-time prune (needs explicit authorization)

The biggest *immediate* win on **existing** rows is `backend/app/db/migrations/007_prune_chunk_metadata.sql` (or `python -m app.ingestion.metadata_pruning`): it rewrites every bloated row to the allowlist **server-side (no egress for the rewrite)**, cutting `chunks.metadata` from ~13 KB to <0.5 KB per row.

> ⚠️ This is a **destructive, irreversible production-data migration** (the stripped EPrints/links keys are not stored elsewhere). It was **not run automatically** — it is staged for you to review and execute. After it runs, retrieval egress drops immediately; storage is reclaimed by VACUUM/autovacuum.

## Expected impact

| | Before | After (code) | After (+ one-time prune) |
|---|--:|--:|--:|
| metadata/row | ~13 KB | ~13 KB (existing) / <0.5 KB (new) | **<0.5 KB** |
| egress / repeated query | ~4 MB | **~0 (cache hit)** | ~0 |
| egress / unique query | ~4 MB | ~4 MB (existing rows) | **~1.5 MB** |

With caching alone, repeated-query egress drops to ≈0; with the prune, even unique-query egress falls ~70%. Configure `REDIS_URL` to share the cache across backend workers.

## Settings (new)
`CACHE_ENABLED` (true) · `CACHE_TTL_SECONDS` (300) · `REDIS_URL` (optional) · `FAQ_CACHE_TTL_SECONDS` (600) · `RETRIEVAL_CACHE_ENABLED` (true) · `RETRIEVAL_CACHE_TTL_SECONDS` (300).
