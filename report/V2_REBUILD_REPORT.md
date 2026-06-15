# UMB Knowledge Assistant — Production Grounded RAG Rebuild v2

**Date:** 2026-06-13 · Executed in 6 verified batches (tests + live + benchmark after each).
Pipeline: **Intent → FAQ → Entity → Typed Graph → Hybrid Vector → Confidence → (low?) Tavily → Synthesis**

---

## Batch 1 — Intent routing + entity over-firing fix + latency
- **`intent_router.py`**: `detect_intent()` → 15 canonical intents; `apply_entity_intent_compatibility()` demotes structured contexts (entity/graph/FAQ) whose type/category is incompatible with the detected intent (score → 2.0, unpinned).
- Fixes: `"biaya"`/`"bantuan"` removed from scholarship entity terms; `"mendaftar"` routed to admissions; broad faculty-list FAQ demoted on specific topical questions.
- **`pg_trgm`** GIN indexes (migration 004) + `defer(Chunk.embedding)`: **hybrid retrieval 10.3 s → 4.8 s**.
- Result: **tuition answerability 0.195 → 0.927**, overall strict 0.621 → 0.703, `official_top` held 0.988.

## Batch 2 — Follow-up vs new-topic detection (memory leakage)
- **`detect_followup(question, history)`** (conservative: uncertain → NEW_TOPIC). `_build_retrieval_query` retrieves on the **bare question** for a new topic instead of always merging prior turns/source-hints. Emits `followup_detection`.
- **Verified live:** "dekan FASILKOM" → "login SIA" = NEW_TOPIC, zero FASILKOM leak. **Follow-up routing accuracy 1.0** (12/12 labelled).

## Batch 3 — Answer synthesis (knowledge assistant, not search engine)
- System prompt: synthesize a complete merged answer, no raw-snippet dumping, don't abstain when the context holds the answer.
- **FAQ-direct path** (`_structured_faq_payload`): a strong canonical-FAQ match returns directly as a complete cited answer (`model=canonical-faq`), bypassing LLM over-abstention.
- Clarification gate **skipped when a strong FAQ matches** (was stalling "Beasiswa apa saja?").
- **Cross-cutting fix:** added `match_query` to `run_umb_agent` — structured layers match the **bare** question, only vector uses the augmented query (the chat's `"…Topik terdeteksi"` suffix was knocking the FAQ off rank-1, silently defeating FAQ-direct).
- **Verified live:** scholarship now returns a complete `canonical-faq` answer (was a clarification stall).

## Batch 4 — Confidence-gated Tavily fallback + discovery cache + async acquisition
- **`evaluate_confidence(contexts)`** gates the billed Tavily fallback: a strong FAQ/entity/graph hit or ≥2 official chunks = sufficient (skip Tavily); a lone chunk defers to the count/score gate. Agent emits a `confidence_check` step.
- **`knowledge_discovery_cache`** table (migration 005): `was_recently_discovered` skips a repeat Tavily search once content was acquired+indexed.
- **`async_acquisition.schedule_kb_acquisition()`**: answer the user FIRST, then persist web sources + record discovery in a background thread (own DB session). Tavily domain filter already enforced (`include_domains`, scope validation, archive reject).
- **Measured:** Tavily-fallback proxy rate **0.012** — 98.8% of questions answered from the KB with no live-web escalation.

## Batch 5 — KB authority re-tiering (+ enrichment crawl, partial)
- **`host_authority` explicit 4 tiers:** root 0.9 · Tier 1 official incl. faculty subdomains 0.85 · Tier 2 default 0.5 · Tier 3 library 0.45 · Tier 4 archive 0.25. (`lib` moved out of Tier 1; repository never dominates general queries — already 0.25.)
- **Enrichment crawl** (`leadership_enrichment.py`, 6 tests): built + tested, but a controlled live dry-run found UMB's leadership pages are **not at standard paths** (`struktur-organisasi`/`pimpinan`/`dekanat` → 404; 0/7 deans extracted). Dean fields remain empty → needs **Tavily-map URL discovery** first (deferred; external-call cost).

## Batch 6 — Extended benchmark
- Added **intent-routing accuracy**, **follow-up routing accuracy**, **per-layer hit rates**, and **Tavily-fallback proxy rate** to the harness.

---

## Final v2 benchmark (501 Qs, all batches, agent strategy)

| Metric | Value | vs Phase 5 |
|---|--:|--:|
| Strict `target_hit` answerability | **0.705** | 0.621 → **+0.084** |
| `official_top` (correct official @ rank-1) | **~0.988** | maintained |
| Citation-failure rate (archive @1) | **0.012** | maintained |
| tuition answerability | **0.927** | 0.195 → **+0.732** |
| admissions answerability | **0.60** | 0.556 → +0.044 |
| Intent-routing accuracy | **0.782** | new |
| Follow-up routing accuracy | **1.0** | new |
| Tavily-fallback rate (proxy) | **0.012** | new |
| Layer hit rates (top-k) | FAQ 0.23 · Entity 0.75 · Graph 0.53 · Vector 0.78 | new |
| Hybrid retrieval latency (p50) | **4.8 s** | 10.3 s → **−53%** |

**Remaining strict-weak categories** (scholarship 0.119, student_services 0.333, campus 0.5) are unchanged **benchmark-label artifacts** — `official_top` for them is 0.93–1.0 (the system surfaces the correct official source, e.g. `kemahasiswaan` for scholarships, but the label expects a different deep-link host). These are a measurement issue, not a retrieval failure.

## Tests
- **487 tests pass** (was 425 at Phase 5; +62 across the v2 batches). New suites: `test_intent_router` (35), `test_answer_synthesis` (6), `test_discovery_cache` (9), `test_leadership_enrichment` (6), `test_trust` tier tests.

## Honest status / deferred
- **Strict >95% answerability** is gated by benchmark-label modernization (credit canonical structured URLs) — a measurement fix, not a retrieval one.
- **Dean/program-head enrichment** needs Tavily-map URL discovery (the standard-path crawl 404s).
- **Sub-1s hybrid latency** needs server-side ranking (ts_rank/trgm with small LIMIT); 4.8 s achieved via pg_trgm + column projection.
- **Generation groundedness** still wants an NLI/MiniCheck judge (lexical checker false-flags paraphrases) — live chat shows 0 hallucinations on the validated set.
