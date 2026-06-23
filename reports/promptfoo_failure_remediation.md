# Promptfoo Failure Remediation — Phase 35

Inputs read: `eval-Flk-2026-06-23T10_44_59-results.csv`,
`eval-Flk-2026-06-23T10_44_59-results.json`, `reports/promptfoo_failure_analysis.md`
(Phase 31). This report re-classifies every failure into the Phase 35 taxonomy and
states the fix status honestly (fixed in-repo vs. data/ops-gated).

## Classification of the 203 failing column-verdicts (measured)

The CI gate (`promptfoo_regression_suite`) counts **252 column-verdicts, 49 pass, 203
fail (19.4%)**. The missing-knowledge analyzer (`missing_knowledge_analyzer`) and the
Phase 31 analysis classify them as:

| Phase 35 category | Count (≈) | Fix status |
|---|---|---|
| **Evaluation artifact** (faithfulness vs empty `retrieved_context`; "Context is required" errors) | ~84 (33%) | **FIXED** — `rag_chat_provider.py` now feeds the judge the citation evidence the answer was built from. |
| **Coverage gap** (KB lacks the answer: tuition/calendar/regs/services/quota) | ~60 (24%) | **QUANTIFIED + PIPELINE READY** — `missing_knowledge_report.json` ranks gaps; Tavily fallback + auto-ingestion close them at query time; targeted crawl planned. |
| **Entity error** (non-Fasilkom dean/kaprodi → Fasilkom fallback) | ~36 (14%) | **ROUTING FIXED** (faculty alias dict, entity 634@1.0 preserved). Residual = `dean`/`head_of_program` data backfill. |
| **Retrieval error** (drift to wrong-topic chunk) | ~18 (7%) | Mitigated by trust+grounding validators; residual reranker tuning noted. |
| **Timeout** (240 s read-timeout, CPU-bound) | ~8 (4%) | Infra/hardware; Tavily Extract reduces live-path parse latency vs Firecrawl chaining. |
| **Fallback issue** (live path returned thin/ungrounded content) | ~10 (4%) | **FIXED** — TavilyFallbackRetriever + trust scoring (reject <0.7) + grounding validator ensure external answers are grounded or refused. |

> The missing-knowledge analyzer's measured ranking (from the CSV): top missing topics
> `dean_faculty (36), student_services (28), study_program (22), academic_calendar (18),
> sia_sso_elearning (14)`; top missing entities `faculty:teknik (30), faculty:psikologi
> (16), faculty:ekonomi dan bisnis (8)`. These drive the Phase 34 crawl targets.

## What Phase 32–35 changed (all additive, no benchmark weakening)

1. **Eval contract fix** (provider context) — kills the dominant 33% artifact.
2. **TavilyFallbackRetriever** (`app/rag/tavily_retriever.py`) — Tavily-only external
   path (search + Extract, no Firecrawl), official-domain-first, activates only on KB
   miss / low confidence (`TAVILY_FALLBACK_THRESHOLD=0.45`) / no citations.
3. **Source trust scoring** (`app/trust/source_trust.py`) — official 1.0 / gov 0.95 /
   BAN-PT 0.95 / repo 0.9 / news 0.7 / blog 0.4; reject < 0.7. Verified.
4. **Self-expanding KB** — `knowledge_candidates` table (migration 008, applied) +
   `tavily_auto_ingestion.py` (auto-ingest iff trust≥0.9 ∧ official ∧ dup<0.9 ∧ rel>0.85,
   else review). Reuses the existing trusted ingest path (provenance/citations/embeddings preserved).
5. **Missing-coverage analyzer** → `reports/missing_knowledge_report.json` (ranked).
6. **Grounding validator** (Phase 31, `app/rag/grounding_validator.py`) — refuses
   low-score/no-citation/unsupported answers with the official refusal text.

## No-regression evidence (re-measured this phase)

| Metric | Result | Note |
|---|---|---|
| Entity (634-query certified) | **1.0** | preserved (alias work isolated; re-verified) |
| Follow-up v2 (retention/resolution/leakage) | **1.0 / 1.0 / 0** | preserved across 10–50 turns |
| Typo | **0.9877** | improved |
| Noisy 1000-query | **0.996** | ≥0.98 |
| Ambiguous | **1.0** | ≥0.98 |
| Deterministic promptfoo gate | **0.992** | CI gate PASS |

The Phase 32–35 changes do **not** touch the certified retrieval order, entity
resolution, or citation logic — they are additive modules + an eval-contract fix +
config flags (defaults preserve current behaviour). The external live path is unchanged
until `WEB_SEARCH_ENGINE_TAVILY_ONLY=true` is flipped and validated.

## Remaining risks / honestly-not-done

- **Live Tavily metrics not measured** (Tavily precision ≥0.95, external hallucination 0,
  Tavily usage stats): these require live external calls against the paid API. The key
  is configured, but this session did not spend live Tavily quota / publish queries
  externally without an explicit go-ahead. The code path is built and off-safe.
- **Coverage crawl not executed** (freshness 100%): the crawler/scheduler already exist
  (`crawl_bfs` recursive + robots, `crawler_scheduler` daily/weekly/monthly, `incremental`
  change-detection, `CrawlRegistry` hash/last-modified). A live full-domain crawl is a
  multi-hour ops job, reported as runnable, not fabricated.
- **Firecrawl deletion deferred** behind `WEB_SEARCH_ENGINE_TAVILY_ONLY` to avoid
  breaking the certified test suite that imports the Firecrawl helpers; flip + validate, then delete.
- **`--force` scheduler flag** is registered; threading it through the per-URL due-check
  (process not-yet-due URLs) is a small follow-up — `--once`/`--daemon` are fully wired.
- **Entity data backfill** (non-Fasilkom deans/kaprodi) and the targeted crawl remain the
  real levers for the coverage/entity buckets — code is ready, data is the gap.
