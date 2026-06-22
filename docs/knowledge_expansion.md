# Hybrid Knowledge Expansion (Phase 28)

## P28.1 — Tavily fallback search (KB-first, trusted-domain only)
The agent is **KB-first**: it answers from local pgvector/GraphRAG/entity retrieval. When
indexed confidence is low it can fall back to a live web search restricted to official
domains, then synthesize a cited answer (no hallucination — unverified results are refused).

- Implemented by `app/web_search/live_retriever.py` (`UMBLiveWebRetriever`) +
  `app/web_search/tavily_client.py`, wired into the agent via the `web` / `hybrid`
  retrieval modes (`web_tool` in `app/agent/umb_agent.py`).
- **Trusted domains:** `*.mercubuana.ac.id` (scope validator) + official accreditation
  agencies (see `knowledge_ingestion_pipeline._ACCREDITATION_DOMAINS`).
- Every web result carries **source URL + crawl timestamp + confidence**; answers keep
  citations; low-confidence/untrusted results are dropped (safe refusal preserved).
- **Activation:** set `TAVILY_API_KEY` (+ `WEB_SEARCH_ENABLED=true`). Without a key the
  fallback is a no-op and the system uses the certified KB-only path. (Not exercised in
  this offline environment — requires the key + network.)

## P28.2 — Auto knowledge injection
`app/ingestion/knowledge_ingestion_pipeline.py` → `ingest_web_result(db, url, content, …)`.
Pipeline: **gate → clean → chunk → embed → insert → provenance → freshness → registry.**

Gates (all required, else rejected — zero duplicate growth, provenance 100%):
- `is_trusted(url)` — trusted domain only.
- `relevance >= threshold` (default 0.6).
- **not duplicate** — `content_hash` checked against `sources`; reuses the dedup-aware
  `upsert_source_document` (skips re-chunking on identical content).

On success: chunks embedded via `backfill_embeddings` (new chunks only); source marked
`indexed` with `first_seen_date`/`last_verified_date`/`extraction_date`; URL registered in
`crawl_registry` for future change detection. Returns an `IngestionResult` provenance record.

## P28.3 — Full Mercu Buana re-crawl
Use the existing incremental crawler (Phases 17/19) for comprehensive coverage across all
official domains/subdomains (academic, administration, campus, student affairs, digital
services, regulations, FAQ) including PDFs/DOCX/reports/decrees/handbooks.

```bash
cd backend
# 1) classify cadence (archive=monthly), then crawl due URLs (recursive + sitemap + PDF)
python -m app.crawl.crawler_scheduler --reclassify
python -m app.crawl.crawler_scheduler --tick           # live HttpFetcher + re-ingest changed
# 2) coverage / gap reports
python -m app.evaluation.crawl_efficiency --out ../reports/crawl_efficiency_report.json
```
Crawler capabilities (implemented): recursive crawling, sitemap discovery, PDF extraction,
content-hash duplicate detection, freshness metadata, host-authority scoring.

**Deliverables when run live** (require network access to mercubuana.ac.id, unavailable in
this offline env): `crawl_coverage_report.json`, `domain_inventory.json`,
`knowledge_gap_analysis.json`. The framework + commands are in place; a live run on a
networked host is needed to realize the ≥50% coverage increase. Current KB: 5,911 chunks /
3,066 sources (post-prune, certified).

## Honest status
- P28.1 fallback + P28.2 injection pipeline: **implemented + import-safe**, gated behind
  `TAVILY_API_KEY` / trusted-domain + relevance + dedup checks.
- P28.3 full re-crawl: **framework ready**, not executed here (needs live network). No
  KB regression — these are additive, dedup-guarded paths.
