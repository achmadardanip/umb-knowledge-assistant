# Retrieval Architecture Audit — Phase 32 (P32.1)

Grounded audit of the live retrieval stack as it exists in the repo (read, not assumed).

## 1. Headline findings

- **"Putter.js" does not exist** in this codebase. A full search for
  `putter | puppeteer | playwright | selenium` returns **zero** matches. There is no
  browser-automation / headless-browser search adapter to remove.
- **Tavily is already the external search engine** and is **already live**
  (`TAVILY_API_KEY` is configured, `WEB_SEARCH_ENABLED=true`,
  `web_search_strict_domain=mercubuana.ac.id`). It is **already domain-scoped**
  (`site:mercubuana.ac.id` + `include_domains=[mercubuana.ac.id]`).
- The actual "extra external dependencies" beyond Tavily are **two page-parsers**:
  **Firecrawl** (`fetch_firecrawl_contexts` → `FirecrawlClient`) and a **direct HTTP
  fetcher** (`fetch_live_contexts`). The directive's "Tavily is the only external
  retrieval provider" therefore maps to: **replace Firecrawl page-parsing with Tavily
  Extract**, and demote the direct fetcher to in-house file extraction only.

## 2. Current retrieval order (verified in `app/agent/umb_agent.py`)

```
FAQ (faq_retriever.match_faq)
  ↓
Entity Graph (entity_retriever.query_entities → umb_* tables)
  ↓
GraphRAG (typed in-memory graph)
  ↓
Hybrid Retrieval (HybridRetriever: pg_trgm keyword + pgvector dense + reranker)
  ↓   [KB-first gate: _indexed_is_strong → skip web if ≥3 contexts and top score ≥1.2]
Live Web (UMBLiveWebRetriever):
     Tavily search  →  Firecrawl parse  →  (fallback) direct fetch + local extractors
  ↓
Citation validation (citation_validator tool)
  ↓
LLM (grounded generation)
```

This already matches the target flow, **except** the live-web step uses Firecrawl +
direct-fetch instead of Tavily-only. The KB-first gate (`_indexed_is_strong`,
`web_fallback_min_contexts=3`, `web_fallback_min_score=1.2`) is the existing analogue of
the requested `TAVILY_FALLBACK_THRESHOLD` activation policy.

## 3. External dependencies (the real list)

| Dependency | Module | Role | Keep / consolidate |
|---|---|---|---|
| **Tavily** | `app/web_search/tavily_client.py` | search + map + extract (domain-scoped) | **KEEP** — the only external engine |
| **Firecrawl** | `app/web_search/live_fetcher.py::fetch_firecrawl_contexts`, `app/ingestion/firecrawl_client.py` | external page→markdown parser in the live path | **CONSOLIDATE** → Tavily Extract |
| Direct HTTP fetch | `app/web_search/live_fetcher.py::fetch_live_contexts` | direct GET + local PDF/DOCX/… extractors | **DEMOTE** — keep file extractors (used by crawler), drop from live fallback |
| VA-JIT re-verify | `umb_agent._maybe_va_jit` | volatility/freshness just-in-time re-verify via `live_retriever.search` | inherits Tavily once live path is Tavily-only |

`app/discovery/*` (domain_discovery, scope_validator, url_normalizer) are **in-house**
(no third-party engine) and are reused by Tavily for scope validation — keep.

## 4. Dead / unused / duplicate code

- `app/web_search/live_retriever.py` chains Firecrawl→direct-fetch per result. Once the
  Tavily-Extract path is active, the Firecrawl branch is **dead in the live path**
  (still imported by tests). Staged for removal behind `WEB_SEARCH_ENGINE_TAVILY_ONLY`
  rather than hard-deleted, so the certified test suite never breaks silently.
- `TavilyClient.map` / `TavilyClient.extract` exist but are **not used by the live
  retriever** today — duplicate of the Firecrawl capability. Phase 32 puts `extract` to
  work, removing the duplication.
- `app/web_search/live_retriever.py` and `__init__.py` are thin; no other dead providers
  found (no serpapi/bing/google/duckduckgo wrappers in application code — the
  `data/skills/tavily-*` entries are CLI skills, not app code).

## 5. Retrieval latency (from the Phase 31 CSV + config)

- Structured layers (FAQ/entity/graph/hybrid) dominate when the KB-first gate passes:
  low single-digit seconds on warm cache.
- The live-web path is the latency tail: `web_search_timeout_seconds=6` per Tavily call,
  plus Firecrawl/direct-fetch parse per URL. The Phase 31 CSV shows the worst tails
  (240 s timeouts, 393 s) correlate with the live path + CPU-bound generation. Moving to
  Tavily Extract (single API call returning clean markdown) **reduces** per-URL parse
  latency vs. Firecrawl-then-direct-fetch chaining.

## 6. Target architecture (Phase 32 end-state)

```
FAQ → Entity Graph → GraphRAG → Hybrid (keyword+dense)
      ↓ (KB-first gate / retrieval_confidence ≥ TAVILY_FALLBACK_THRESHOLD)
   [skip external]
      ↓ (confidence < threshold OR no citations OR KB empty)
   TavilyFallbackRetriever  → Tavily search (official-domain-first) → Tavily Extract
      ↓
   Source trust scoring (reject < 0.7)
      ↓
   Grounding Validator (reject low-score/no-citation/unsupported)
      ↓
   LLM (grounded; external answers never ungrounded)
```

## 7. Recommended changes (and risk)

| Change | Risk | Mitigation |
|---|---|---|
| Add `TavilyFallbackRetriever` (Tavily search + Extract, official-domain-first) | Low (additive) | off-safe without key; existing path untouched until flag flips |
| Add source trust scoring + reject < 0.7 | Low | pure function, unit-tested |
| Route live path via Tavily Extract behind `WEB_SEARCH_ENGINE_TAVILY_ONLY` | Medium | flag default preserves current behaviour; flip after live validation |
| Hard-delete Firecrawl/direct-fetch from live path | **Medium-High** | **deferred** — would break `test_web_kb_ingest` etc.; do after Tavily-only is validated end-to-end with the live key |

**Decision flagged to the operator:** the only genuinely destructive step (deleting the
Firecrawl live-parse path) is staged behind a config flag rather than executed now,
because it is hard to reverse and the certified test suite imports those helpers. Flip
`WEB_SEARCH_ENGINE_TAVILY_ONLY=true`, validate a live run, then delete.
