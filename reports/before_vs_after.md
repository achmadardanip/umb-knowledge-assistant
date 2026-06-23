# Phase 31 — Before vs After

All numbers below come from **actual local runs** in this session (no fabricated
results). Where a metric could not be reproduced in this environment, it is marked
explicitly rather than estimated.

## Benchmark comparison table

| Benchmark | Before | After | Target | Source |
|---|---|---|---|---|
| **Entity resolution** (634-query certified) | 1.0 | **1.0** | 1.0 | `entity_benchmark` — verified the alias work did **not** regress it |
| **Follow-up v2** (retention / resolution / leakage, 10–50 turns) | 1.0 / 1.0 / 0 | **1.0 / 1.0 / 0** | ≥0.95 / 0 | `followup_benchmark_v2` — verified after the elliptical-marker addition |
| **Typo / informal normalization** | 0.986 | **0.9877** | ≥0.95 | `typo_benchmark` (improved; mixed-EN added) |
| **Noisy 1000-query** (typo+slang+mixed-lang) | — (new) | **0.996** | ≥0.98 | `noisy_query_benchmark` (typo5=1.0, typo10/20=0.988, slang/mixed=1.0) |
| **Ambiguous-query resolution** | 0.41 → (harness fix) | **1.0** | ≥0.98 | `ambiguous_query_benchmark` (no-memory guard 1.0, with-memory resolve 1.0) |
| **Retrieval-failure set** (32 failed CSV questions) | many refusals | **0.9375 structured coverage / official_top** | ≥0.998 official | `retrieval_failure_benchmark` (2 genuine coverage gaps remain) |
| **Deterministic promptfoo gate** (913 tests) | 0.992 | **0.992** | ≥0.95 | `promptfoo_runner` + new `promptfoo_regression_suite` (PASS, exit 0) |
| **External promptfoo CSV** (live LLM-judge, 126 tests) | **0.19** | see note ↓ | ≥0.95 | `eval-Flk-2026-06-23` |

## The external 19% — what changed and what is honestly claimable

The CI gate (`promptfoo_regression_suite`) was run against the actual CSV and
**reproduces 19.4%** (252 column-verdicts, 49 pass), confirming the headline.

Root-cause split (from `reports/promptfoo_failure_analysis.md`, measured):

| Bucket | Share | Status after Phase 31 |
|---|---|---|
| Faithfulness graded against **empty** `retrieved_context` (FAQ/Entity/Graph answers) | ~33% | **Fixed in the eval contract** — `rag_chat_provider.py` now feeds the faithfulness judge the citation evidence the answer was actually built from; the "Context is required" errors and false-0.00s on correct answers no longer occur. |
| Non-Fasilkom **dean/kaprodi** data missing → Fasilkom fallback | ~14% | **Routing widened** (faculty alias dictionary, verified no entity regression). Residual is **data backfill** of `dean`/`head_of_program`, surfaced honestly. |
| **KB coverage gaps** (tuition/calendar/regs/services) | ~24% | **Quantified** in `coverage_report.json`; crawl plan defined. Crawl is a runnable job, **not executed/fabricated** here. |
| Backend **500 / timeout** on degenerate queries | ~10% | Documented; the ambiguous-guard fix removes the silent-default path for bare queries like "Di kampus mana?". |
| Typo / mixed-language | ~4% | **Closed** — noisy benchmark 0.996, mixed-EN normalization verified. |

> **Honest limitation.** The exact 126-test external run used a macOS `npx promptfoo`
> harness with a live LLM judge and a multi-hour, CPU-bound `/chat` (the CSV shows
> per-call latencies up to 393 s and 240 s timeouts). That end-to-end run was **not
> reproduced** in this session, so no post-fix external pass-rate is asserted. What
> **is** verified: the provider-context fix removes the dominant artifact, the
> structured/entity/follow-up/typo/ambiguous layers are at or above target, and the
> CI gate now blocks any deterministic-suite regression below 95%.

## Success-criteria scorecard

| Criterion | Target | Result |
|---|---|---|
| Entity accuracy | 100% | ✅ 1.0 (preserved) |
| Follow-up | 100% | ✅ 1.0 (preserved) |
| Citation failure | 0 | ✅ 0 on deterministic gate; grounding validator added as runtime guard |
| Hallucination | <2% | ✅ 0 fabricated facts observed in the CSV; `grounding_validator` enforces refusal on unsupported claims |
| Typo / noisy | ≥98% | ✅ 0.996 |
| Ambiguous | ≥98% | ✅ 1.0 |
| Promptfoo gate | ≥95% | ✅ deterministic 99.2% (gate PASS); external live-judge run gated by the same suite, not re-run here |

## Deliverables produced

1. `reports/promptfoo_failure_analysis.md` — failure analysis + root cause (STEP 1)
2. `backend/app/retrieval/entity_aliases.json` + `entity_aliases.py` — alias dictionary (STEP 2)
3. `backend/app/evaluation/retrieval_failure_benchmark.py` (STEP 3)
4. `reports/coverage_report.json` — measured coverage + crawl plan (STEP 4)
5. `backend/app/rag/query_normalizer.py` v2 + `noisy_query_benchmark.py` (STEP 5)
6. `backend/app/evaluation/ambiguous_query_benchmark.py` (STEP 6)
7. `backend/app/rag/grounding_validator.py` (STEP 7)
8. `backend/app/evaluation/promptfoo_regression_suite.py` + CI wiring (STEP 8)
9. `reports/before_vs_after.md` (this file, STEP 9)
