# Phase 6 · P1 Golden Dataset + P4 Mini-Validation + P2 Coverage Dry-Run

**Date:** 2026-06-16 · Evaluation-quality + coverage-projection work (no retrieval
redesign, no live spend, no DB writes).

---

## P1 — Golden Dataset framework ✅

`app/evaluation/golden_dataset.py` builds the dataset from **authentic, in-repo,
KB-grounded sources** (never fabricated user data); synthetic paraphrases are tagged
`synthetic: true` with a `derived_from` pointer (full traceability).

**Schema** (`data/golden_dataset/golden_dataset.jsonl`):
`id, question, intent, expected_sources, answerable, synthetic, source_type,
created_at, dataset_version` (+ `derived_from`, `category`, `lang` where applicable).

**Generated (`--target 1200`):**

| source_type | count | synthetic |
|---|--:|:--:|
| benchmark_seed | 491 | false |
| faq_alias | 81 | false |
| official_faq | 17 | false |
| entity_lookup | 59 | false |
| **authentic subtotal** | **648** | |
| synthetic_variant | 552 | true |
| **total** | **1200** | |

- **648 authentic** (clears the Phase-1 300–600 floor) / **552 synthetic** → 1200 total
  (Phase-2 1000–2000 range). `answerable_ratio` 0.992, `synthetic_ratio` 0.46.
- 14 intents represented (study_program 214, admissions 121, scholarship 110, …).
- **Multi-turn follow-up format** (`golden_dataset_followups.jsonl`, 348 conversations)
  integrates the P3 `followup_context_benchmark.json` as
  `{conversation, expected_followup, expected_intent}`.
- Stats: `data/golden_dataset/golden_dataset_stats.json`.
- Tests: `test_golden_dataset.py` (8) — required metadata, authenticity invariant +
  traceability, Phase-1 floor, no-duplicates, control-unanswerable, stats shape, follow-up format.

## P4 — Mini-validation runner ✅ (built + unit-tested; live run blocked by hardware)

`app/evaluation/golden_validation.py` runs the groundedness pipeline over a golden-dataset
subset and aggregates the five Phase-6 metrics — **groundedness, citation_alignment,
unsupported_claim_rate, regenerate_rate, abstain_rate**. Generation is injected, so the
aggregator is unit-tested here (`test_golden_validation_aggregates_five_metrics`) without
the heavy LLM path.

⚠️ **The live `CGCV_ENTAILMENT_MODE=nli` + `GROUNDEDNESS_DECISION_ENABLED=true` run on
50–100 questions could not execute on this box:** loading the NLI model OOMs
(`memory allocation … failed`) and the generation tier exceeds Ollama's 180 s/question on
CPU — the same memory/throughput ceiling that fails the Qwen3 reranker test. The runner is
ready; run it on a GPU/larger-memory host:

```bash
CGCV_ENTAILMENT_MODE=nli GROUNDEDNESS_DECISION_ENABLED=true \
  python -m app.evaluation.golden_validation --limit 50
```

`citation_alignment` is LLM-free and can be reported from any run.

## P2 — Coverage-expansion DRY RUN ✅ (projection only)

`app/discovery/coverage_expansion_dryrun.py` — pipeline `Map → Discovery → Classification
→ Authority → Projection → Report`. **No Tavily calls, no DB writes, no embeddings, no
ingestion.** Classification reuses the real `validate_url_scope` (drops login/sensitive,
stateful, non-knowledge URLs) + `host_authority` (drops archive/repository below 0.4).

**Projection (`reports/coverage_expansion_report.json`):**

| | value |
|---|--:|
| priority domains | 7 (pmb, pendaftaran, sia, sso, bti, support, baa) |
| pages accepted / discovered / rejected | 2,200 / 3,144 / 944 |
| projected chunks | 8,800 |
| projected storage | 24.84 MB |
| projected Postgres growth | 32.28 MB |
| projected Tavily usage | 20 map + 110 extract calls |

When a real (post-approval) Tavily-Map URL list is supplied via `--urls-file {domain:[urls]}`,
the same code classifies the actual URLs instead of projecting. Tests:
`test_coverage_expansion.py` (4) — archive/login/external rejection, pure-projection totals,
real-URL classification, all priority domains official/high-authority.

---

## Known Environment Issue — Qwen3 Reranker
See `KNOWN_ISSUES.md`. Category: Resource Exhaustion (Windows paging-file/OOM during
transformer load). Production risk: low. Not caused by P3/P4/P1/P2 (proven via `git stash`
at the green P3 commit; passes earlier in-session and standalone once memory is freed).

## Net test delta this session
P3 (+4) → 567 · P4 (+9) → 576 · P1/P4-val/P2 (+12) → **588 tests**, all passing except the
one environment-bound reranker test.
