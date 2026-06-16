# Phase 6 · Priority 4 — Groundedness Verification

**Date:** 2026-06-16 · Extends the existing CGCV trust gate (no retrieval redesign).
Goal: measure and act on whether a generated answer is actually supported by its cited
evidence — `Retrieve → Rank → Generate → Verify → Groundedness Score → Decision`.

---

## What shipped

### 1. Better entailment engines (`app/verification/entailment.py`)
The CGCV gate depends only on the `EntailmentChecker` protocol, so the engine is
swappable. Added two upgrades over the paraphrase-false-flagging `LexicalEntailmentChecker`:
- **`NLIEntailmentChecker`** — cross-encoder NLI (`mDeBERTa-v3-xnli-multilingual` by
  default); returns the model's ENTAILMENT probability, so a genuinely-entailed
  paraphrase scores high without token overlap. Multilingual (ID + EN). Model is
  **lazy-loaded**; construction raises if torch/transformers/weights are missing.
- **`MiniCheckEntailmentChecker`** — wraps the optional `minicheck` package when installed.

Both are import-guarded so an offline host degrades cleanly.

### 2. Groundedness verifier + decision (`app/verification/groundedness.py`)
- **`build_groundedness_checker(preference)`** — constructs the best available checker;
  `auto` order **MiniCheck → NLI → LLM-judge → Lexical**. Never raises (falls through).
- **`GroundednessVerifier.verify(answer, contexts_by_citation) → GroundednessResult`**
  scores `supported_claims / total_claims` (1.0 if the answer asserts no claims) and
  recommends a decision per the Phase-6 thresholds:

  | groundedness | decision |
  |---|---|
  | ≥ 0.90 | `return` |
  | 0.70 – 0.90 | `regenerate` (once) |
  | < 0.70 | `abstain` (official sources only) |

  `GroundednessResult` also carries `unsupported_claim_rate` and `citation_alignment`.

### 3. Decision gate wired into generation (`app/rag/answer_generator.py`)
- `_apply_groundedness_decision()` runs in `finalize_generated_answer` **after** citation
  validation + CGCV, **only when `GROUNDEDNESS_DECISION_ENABLED=true`** (off by default —
  it adds an entailment pass per answer; enable on a GPU verifier host). On `abstain` it
  drops the unsupported answer text but **keeps the official source cards**, and records
  `metadata.groundedness = {score, decision, unsupported_claim_rate, citation_alignment, checker}`.
- `build_default_entailment_checker` now also accepts `CGCV_ENTAILMENT_MODE = nli | minicheck | auto`,
  so the **always-on CGCV gate itself** can use the NLI checker (the real production win —
  fewer correct answers wrongly dropped by the lexical checker), degrading to lexical when
  the model is unavailable.

### 4. Metrics (`app/evaluation/metrics.py`)
- `unsupported_claim_rate` — direct hallucination signal (1 − faithfulness).
- `citation_alignment` — structural (no-LLM): fraction of cited claims whose every `[n]`
  maps to an actually-retrieved context (catches dangling/fabricated citation ids).

### 5. Config (`app/core/config.py`)
`GROUNDEDNESS_VERIFIER` (auto), `GROUNDEDNESS_DECISION_ENABLED` (false),
`GROUNDEDNESS_RETURN_THRESHOLD` (0.90), `GROUNDEDNESS_REGENERATE_THRESHOLD` (0.70).

---

## Tests
`test_groundedness.py` (9): return/regenerate/abstain decisions, no-claims = vacuously
grounded, `citation_alignment` dangling-citation detection, `unsupported_claim_rate`,
factory graceful degradation (never raises), custom thresholds, and the finalize abstain
path keeping official sources. Full backend suite re-run for regressions (gate is off by
default → existing behaviour unchanged).

---

## Honesty / limits (targets gated by hardware)
The plan's headline numbers — **groundedness > 95 %, hallucination < 2 %, citation_alignment
> 95 %** — require running the verifier across a generated-answer set, which needs the LLM
generation tier. On this **CPU-only** host that tier exceeds Ollama's 180 s/question timeout
(the same constraint that blocked the v3 generation benchmark), and the cloud fallbacks are
unconfigured/rate-limited. So this priority delivers the **verifier, decision logic, metrics,
and wiring — fully unit-tested and opt-in** — but the corpus-level groundedness/hallucination
figures must be produced on a GPU verifier host (set `CGCV_ENTAILMENT_MODE=nli` +
`GROUNDEDNESS_DECISION_ENABLED=true`). `citation_alignment` is LLM-free and can be reported
now from any benchmark run. This matches the directive's "MiniCheck → NLI → LLM-judge"
preference and leaves a drop-in path for the GPU measurement.
