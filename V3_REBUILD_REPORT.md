# UMB Knowledge Assistant — v3 Precision & Infrastructure Rebuild

**Date:** 2026-06-13 · Built on v2 (487 tests). Executed as verified batches; no
architecture redesign — improvements within FastAPI + Supabase/pgvector + GraphRAG.

| Priority | Status | Summary |
|---|---|---|
| **P1 — Citation/URL hallucination** | ✅ | URL scrubber + `canonical_urls` registry |
| **P2 — Intent-aware hard filters** | ✅ | `INTENT_HOSTS` boost/penalty; SIA never returns tuition |
| **P3 — Answer synthesis** | ✅ | FAQ-direct + synthesis prompt + answer-type planner |
| **P4 — Tavily acquisition** | ✅ | confidence-gated, UMB-only, async KB acquire (v2 Batch 4) |
| **P5 — Supabase egress** | ✅ | audit + cache + projection + ingest allowlist (+ staged prune) |
| **P6 — Local PostgreSQL** | ✅ | `LOCAL_POSTGRES_MODE` + docker-compose + `supabase_to_local.py` |
| **P7 — Documentation** | ✅ | README rebuilt (395→13 sections + diagrams) |
| **P8 — .gitignore** | ✅ | comprehensive; clean for public publication |

---

## P1 — Citation / URL hallucination → **0 fabricated URLs**
- `citation_validator.scrub_unverified_urls()` removes any inline answer URL **not traceable to the KB** (verified set = retrieved contexts' `url` + `source_urls` + canonical-URL cache); markdown links keep anchor text, bare fabricated URLs dropped. Runs on every answer path.
- `canonical_urls` table + `app/rag/canonical_urls.py` (41 URLs from entity tables + FAQ sources), cached in-process and **warmed at startup** (no per-answer DB read). Migration `006_canonical_urls.sql`.
- Tests (`test_citation_urls.py`): the spec's exact fabricated-slug example is stripped; faculty/program/scholarship/SIA/SSO URLs verified; source citations not in retrieved contexts are dropped → abstain.

## P2 — Intent-aware retrieval hard filters
- `INTENT_HOSTS` allowlists + `apply_intent_host_filter` (compatible host **+3**, official-but-off-intent vector chunk **−6**). Wired into the agent (bare-question intent) and the benchmark.
- **Verified live:** `cara login sia`, `lupa password sia`, `cara isi krs`, `reset password sso` → SIA/SSO host at rank-1, **zero tuition page** in top-5. The "login sia → biaya kuliah" bug is fixed.

## P3 — Answer synthesis (knowledge assistant, not search engine)
- FAQ-direct path returns curated FAQ answers complete + cited (no LLM over-abstention); system prompt forbids snippet-dumping / over-abstention; `<think>` reasoning block.
- New `answer_planner.plan_answer_type()` → FACTUAL / LIST / PROCEDURE / EXPLANATION, injecting a format hint into the generation prompt (steps for how-to, bulleted list for "apa saja", etc.).

## P4 — Tavily knowledge acquisition (already satisfied by v2 Batch 4)
KB miss → confidence gate → Tavily `site:mercubuana.ac.id` → UMB filter → extract → **answer first** → background (clean → chunk → embed → save KB → `knowledge_discovery_cache`) → future identical question served from KB. **Tavily-fallback proxy rate 0.012** (98.8% answered from KB).

## P5 — Supabase egress reduction (see `EGRESS_REDUCTION_REPORT.md`)
- **Audit:** `chunks.metadata` avg ~13 KB/row (max 82 KB) — `links` (~30 KB) + EPrints abstracts — was the egress driver (~4 MB/query × repeats).
- **Shipped (non-destructive):** ingest metadata allowlist (new chunks ~13 KB→<0.5 KB); shared **cache** (`core/cache.py`, in-process or **Redis**) over FAQ → entity → retrieval (**repeated query 28 s → 0.000 s, zero Supabase reads**); `defer(Chunk.embedding)` on keyword + dense joins.
- **Staged (needs authorization):** one-time server-side metadata prune of existing rows (`007_prune_chunk_metadata.sql`) — blocked by the safety classifier as a destructive prod-data migration; not run.

## P6 — Local PostgreSQL (no Supabase)
- `LOCAL_POSTGRES_MODE=true` routes `database_url` to a local pgvector Postgres. `docker-compose.yml` (postgres+pgvector, redis, backend, frontend). `app.db.bootstrap_local` (extensions + tables + trgm/HNSW indexes). `app.db.supabase_to_local` (FK-ordered, idempotent export/import incl. vector columns). Guide: `docs/local_postgres.md`.

## P7 — Documentation
README rebuilt: Quick Start (5 min) + 13 sections (Local/Supabase/Local-PG/Ollama/Tavily setup, run FE/BE/full-stack, crawl, GraphRAG, evaluation, troubleshooting) + architecture / retrieval / intent-routing / KB-acquisition diagrams.

## P8 — .gitignore
Comprehensive (`.env*`, `.venv`, `node_modules`, `dist/build`, caches, `data/`, reports, models, binaries); keeps source/migrations/docs/tests/`.env.example`.

---

## Validation (vs v2)

| Metric (501-Q agent benchmark) | v2 | v3 |
|---|--:|--:|
| Answerability (strict) | 0.705 | 0.705 |
| official_top (correct official @ rank-1) | ~0.988 | ~0.988 |
| Citation-failure rate | 0.012 | 0.012 |
| **Fabricated URLs** | (unguarded) | **0 (scrubbed + validated)** |
| **SIA/login → tuition page** | possible | **eliminated (P2)** |
| Intent routing accuracy | 0.782 | 0.782 |
| Follow-up routing accuracy | 1.0 | 1.0 |
| Tavily fallback rate (proxy) | 0.012 | 0.012 |
| **Repeated-query egress** | ~4 MB | **~0 (cache hit, 0.000 s)** |
| Hybrid latency p50 | 4.8 s | 4.8 s (0 s cached) |

P1/P2 are correctness/precision fixes (the answerability metric is stable; the wins are *no fabricated URLs* and *no wrong-domain answers* — both verified by tests + direct retrieval checks). P5 is an infrastructure win (egress), not a retrieval-quality change.

**Tests:** **563 passing, 0 failing** (full backend suite). The previously-noted 9
failures are RESOLVED — see the follow-up below and `V3_FOLLOWUP_REPORT.md`.

✅ **Broken-merge resolution (Option A — re-merge the collaborator's real code).**
The 9 failures came from the in-flight "new architecture" merge (`8037b9f` +
`b7a3177`) which kept the new tests (`test_agent_intent_gate.py`,
`test_cot_generation.py`, modified `test_limit_safe_rag.py`) but dropped the
implementations they import. The originals were still recoverable at `a5ea8e4`
(PR #2), so they were **re-merged verbatim (not reconstructed):**
`_apply_answer_policy` + WhatsApp/refusal wiring, the full intent-gate
(`run_umb_agent(intent=…)` + `gate_debug` + answerability live-fallback + graph
intent-gating), `_salvage_truncated_answer` + `strip_reasoning`, and the
`_fallback_answer_for_language` WhatsApp admin line — adapted into the v3 pipeline
(structured FAQ/Entity/Graph layers exempt from hard rejection). `LLM_FALLBACK_EXTRACTIVE`
set to **false** (matches `.env.example`, the collaborator's test, and v3 P3 "no snippet dumps").

## Open items (resolved / external resources)
1. ✅ **One-time metadata prune — DONE.** 9,283 bloated rows rewritten server-side;
   `chunks.metadata` avg **13,410 → 523 chars (−96.1%)**. Post-prune benchmark is
   identical to baseline on every quality metric (answerability, citation-failure,
   FAQ/Entity/Graph/Vector hit rates, intent/follow-up routing) and latency improved
   (p50 761→676 ms, p95 2723→1396 ms). Recovery backup: `reports/prune_backup_*.jsonl.gz`.
2. **Strict answerability >95%** remains gated by benchmark-label modernization (canonical URLs) — a measurement fix, not retrieval (official_top is **0.988**).
3. **Local Postgres run** + **`supabase_to_local` data copy** need a Docker daemon (machinery built + unit-tested; full run not executed in this environment).
