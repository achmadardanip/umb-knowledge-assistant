# GitHub Actions — Incremental Crawl, Index & Knowledge-Graph Refresh

The repo ships **`.github/workflows/umb-freshness.yml`**, a scheduled job that keeps
the Supabase knowledge base (and the GraphRAG graph) fresh **incrementally** — it
only re-indexes pages whose content hash changed, so daily runs are cheap.

## What it does (in order)

1. **Verify** the Supabase connection.
2. **Merge & filter** discovered URLs (scope: `mercubuana.ac.id` + `*.mercubuana.ac.id`,
   excluding private/login/admin per `robots.txt` and the exclusion rules).
3. **Incremental crawl + index** of public pages (`crawl-discovered`, content-hash
   dedup → unchanged pages are skipped).
4. **Incremental multimodal ingestion** (PDF/PPT/XLS/image extraction).
5. **Rebuild the GraphRAG knowledge graph** (`python -m app.graph.build_graph`).
6. **Upload** sanitized reports + the graph artifact.

## Schedule

```yaml
on:
  schedule:
    - cron: "0 20 * * *"   # daily 20:00 UTC (03:00 WIB)
  workflow_dispatch:        # manual run, with optional inputs
```

## One-time setup

### 1. Add repository secrets
`Settings → Secrets and variables → Actions → New repository secret`:

| Secret | Required | Notes |
|---|---|---|
| `SUPABASE_POOLER_DATABASE_URL` | ✅ (recommended) | Supabase **Session/Transaction Pooler** URI. GitHub runners often can't reach the direct `db.*` IPv6 host — the pooler avoids that. |
| `DATABASE_URL` | fallback | Used only if the pooler secret is unset. |
| `OPENAI_API_KEY` | ✅ | Embeddings on CI (`text-embedding-3-small`) — a separate, reliable quota vs. the rate-limited Gemini key. |
| `TAVILY_API_KEY` | optional | Enables live web enrichment during indexing. |

> The chat app at runtime uses **Puter.js (free, keyless, in-browser)** for generation,
> so no LLM key is needed for *answering*. CI only needs an embedding key for indexing.

### 2. Enable the workflow
`Actions` tab → enable workflows → open **UMB Freshness Crawl**.

### 3. Run it manually (first run / on demand)
`Actions → UMB Freshness Crawl → Run workflow`. Optional inputs:
- `crawl_max_pages` (default `500`)
- `multimodal_max_files` (default `200`)

## Tuning (env in the workflow)
- `SCHEDULED_CRAWL_MAX_PAGES`, `SCHEDULED_MULTIMODAL_MAX_FILES` — per-run budget.
- `DISCOVERY_RATE_LIMIT`, `CRAWLER_RATE_LIMIT` — politeness (req/sec).
- `ALLOWED_DOMAIN` / `DISCOVERY_DOMAIN` — crawl scope (keep `mercubuana.ac.id`).

## Consuming the graph in production
The graph is rebuilt from the DB, so any deployment can regenerate it with
`python -m app.graph.build_graph` (writes `GRAPH_PATH`, default
`data/graph/umb_graph.json`). The workflow also uploads it as a build artifact if you
prefer to download rather than rebuild. If the file is absent, GraphRAG simply no-ops
(retrieval still works) — it never blocks answering.

## Verifying a run
- Green check on the workflow run.
- `data/discovery/discovery_report.json` artifact shows pages crawled/indexed.
- Ask the app a question about a newly-published page — it should cite it.
