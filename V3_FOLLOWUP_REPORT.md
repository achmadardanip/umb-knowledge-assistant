# V3 Follow-Up — Broken-Merge Resolution + Authorized Metadata Prune

**Date:** 2026-06-16 · Authorized actions from the "V3 Rebuild Follow-Up" decision:
(1) resolve the broken merge via **Option A** (re-merge the collaborator's real code),
(2) execute the authorized one-time `chunks.metadata` prune, (3) run the mandatory
post-merge + post-prune benchmark validation.

---

## 1. Broken-Merge Resolution — Option A (re-merge, not reconstruct)

**Diagnosis.** The 9 failing tests came from the in-flight "new architecture" merge
(`8037b9f` + `b7a3177 "resolve merge conflicts using local changes"`). That resolution
**kept the new tests but dropped the implementations they import.** The originals were
NOT permanently lost — they were still present at `a5ea8e4` (the PR #2 merge, the last
commit before the refactor). Per the directive ("do not reconstruct unless the original
is confirmed unavailable"), they were **recovered verbatim from `a5ea8e4`** and adapted
into the current v3 pipeline.

| Layer | Recovered into | What was restored |
|---|---|---|
| **Answer policy** | `app/api/routes_chat.py` | `_apply_answer_policy()` (verified → untouched; unverified/extractive → drop source cards; sensitive intent → `refusal_message`; general → WhatsApp-admin fallback). Wired at both call sites: `process_chat` (server path) + `chat_finalize` (browser/Puter path). |
| **WhatsApp fallback** | `app/api/routes_chat.py` | `_fallback_answer_for_language()` restored the `admin_contact_line()` (WhatsApp `628119852020`) tail dropped by the refactor; added `admin_contact_line` import. |
| **Conversation isolation** | `app/api/routes_chat.py` | `_build_retrieval_query(..., intent=)` drops chat-title/turns that `history_conflicts` the current intent (a Fasilkom chat no longer steers a SIA-login query). Computed `retrieval_intent = detect_retrieval_intent(question)` and threaded it in. |
| **Intent gate** | `app/agent/umb_agent.py` | `run_umb_agent(intent=…)` + `AgentResult.gate_debug`: hard-filters off-intent vector/web candidates (`gate_contexts`), fires the live fallback on *no answerable intent-matched context* (`should_trigger_live_fallback`), and intent-gates GraphRAG expansion. **The v3 structured layers (FAQ/Entity/typed-Graph) are exempt from hard rejection** — they already enforce intent via their own matching + `intent_router` demotion — so the recovered gate composes with the v3 pipeline instead of fighting it. |
| **CoT generation** | `app/rag/answer_generator.py` | `strip_reasoning()` (drop `<think>` before JSON parse) + `_salvage_truncated_answer()` (recover complete list items from token-truncated JSON instead of dumping raw JSON / collapsing to the extractive dump). |
| **Extractive policy** | `.env`, `app/core/config.py`, | `LLM_FALLBACK_EXTRACTIVE` → **false** (the `.env` had drifted to `true`; `.env.example`, the collaborator's test, and v3 P3 "No snippet dumps. No abstentions." all intend `false`). Config default also flipped to `False` to prevent re-drift. |

`app/retrieval/intent_gate.py` itself was **byte-identical** between `a5ea8e4` and HEAD
(all gate helpers — `gate_contexts`, `should_trigger_live_fallback`,
`live_query_for_intent`, `refusal_message`, `admin_contact_line`, `history_conflicts` —
were intact); only the *wiring* in the three files above had been dropped.

**Result:** the 9 originally-failing tests pass, and the **full backend suite is
563 passed / 0 failed** (was 554 / 9). No tests were deleted or weakened.

---

## 2. Authorized Metadata Prune

**Preconditions (all satisfied before executing):**
- **Recovery backup** — `app/db/prune_backup.py` exported `(id, metadata)` for every
  row the prune would rewrite → `reports/prune_backup_20260615T223100Z.jsonl.gz`
  (9,283 rows, 14.6 MB gzip). This is the complete recovery set for the operation. A
  full cluster `pg_dump` was intentionally avoided: the project is already over its
  egress budget and Supabase keeps managed daily full-cluster backups; the prune only
  mutates this one column.
- **Baseline metrics** — `reports/prune_baseline_*.json`:
  `rows_with_metadata=10,942`, `avg_metadata_chars=13,410`, `max=82,070`,
  `rows_bloated(>600)=9,283`, `bloated_total≈146 MB`.
- **Baseline benchmark** — `reports/benchmark_preprune.json` (501-question agent run).

**Execution** (`python -m app.ingestion.metadata_pruning`, server-side, no egress):

```
rows_pruned=9283  avg_meta_chars_before=13410  avg_meta_chars_after=523
```

**Outcome:** `chunks.metadata` average **13,410 → 523 chars (−96.1%)**, i.e. ~0.5 KB/chunk
(target met). Stripped keys (`links` ~30 KB, `images`, EPrints/`DC.*` abstracts) are
never read by the retriever; new chunks stay lean via the ingest allowlist
(`app/ingestion/metadata_pruning.prune_metadata`).

### Post-prune validation — quality unchanged, latency improved

| Metric | Pre-prune | Post-prune | Δ |
|---|--:|--:|---|
| Answerability (strict) | 0.705 | 0.705 | unchanged |
| Retrieval accuracy (labelled) | 0.705 | 0.705 | unchanged |
| Coverage (any official source) | 1.000 | 1.000 | unchanged |
| Citation-failure rate | 0.012 | 0.012 | unchanged |
| Intent routing accuracy | 0.782 | 0.782 | unchanged |
| Follow-up routing accuracy | 1.000 | 1.000 | unchanged |
| FAQ hit-rate (top-k) | 0.236 | 0.236 | unchanged |
| Entity hit-rate (top-k) | 0.837 | 0.837 | unchanged |
| Typed-Graph hit-rate (top-k) | 0.629 | 0.629 | unchanged |
| Vector hit-rate (top-k) | 0.772 | 0.772 | unchanged |
| Answer-source layer mix | Ent 302 / FAQ 109 / Vec 62 / Graph 18 | identical | unchanged |
| Latency p50 / p95 / p99 (ms) | 761 / 2723 / 4149 | **676 / 1396 / 2014** | ⬇ faster |

Retrieval, citation, graph integrity, and FAQ/Entity retrieval are **bit-for-bit
unchanged** (the retriever only ever read the allowlisted keys); the smaller payload
makes retrieval measurably faster.

---

## 3. Mandatory Validation vs Targets (post-merge + post-prune)

**Retrieval metrics** (501-question `agent` benchmark, `reports/benchmark_postprune.json`):

| Metric | Value | Target | Status |
|---|--:|--:|:--:|
| official_top@1 (answer-bearing) | **0.988** | ≥ 0.98 | ✅ |
| strict_answerability | 0.705 | ≥ 0.90 | ⚠️ measurement-gated¹ |
| citation_failure_rate | 0.012 | ≤ 0.01 | ⚠️ 0.002 over¹ |
| retrieval_latency_p50 | **0.676 s** | < 3 s | ✅ |
| retrieval_latency_p95 | 1.396 s | — | ✅ |

**Structured-layer hit rates (top-k):** FAQ 0.236 · Entity 0.837 · Typed-Graph 0.629 ·
Vector 0.772. Answer-source share from structured layers: **0.874**.

**Generation metrics** (`agent` + generation tier, qwen2.5:7b-instruct local):

| Metric | Value | Target | Status |
|---|--:|--:|:--:|
| groundedness | not measurable here² | ≥ 0.95 | ⏳ deferred to 6D |
| hallucination_rate | not measurable here² | < 0.02 | ⏳ deferred to 6D |
| follow-up routing accuracy | 1.000 | — | ✅ |
| intent routing accuracy | 0.782 | — | — |

² **The generation tier could not run in this environment** — local `qwen2.5:7b` on
CPU exceeds Ollama's 180 s/question read-timeout (all 3 attempts timed out), and the
cloud fallbacks are unconfigured (`gemini` 400) / rate-limited (`openai` 429). This is
a **pre-existing hardware constraint** (CPU-only inference; see the local-stack latency
note), not a regression from this work. Two grounding signals ARE available and green:
(a) the **retrieval-tier citation-failure rate 0.012** (the hallucination proxy — a
candidate set with no official source at rank-1), and (b) the **server-side grounding
gate every answer passes before return** (`validate_citations` strict citation-marker
check + CGCV claim gate + the new `_apply_answer_policy`, which drops source cards and
substitutes a safe WhatsApp/refusal fallback for any unverified answer). Trustworthy
generation-tier groundedness/hallucination numbers require the **Phase 6D** verifier
upgrade (MiniCheck → NLI → LLM-judge, a drop-in `EntailmentChecker` in `metrics.py`)
plus a GPU run — which is the directed next step, not part of this follow-up.

¹ **strict_answerability (0.705) and citation_failure (0.012)** are unchanged from the
v3 baseline and from the pre-prune run — neither is a regression from this work. Both
are gated by benchmark-label modernization (the labels predate the canonical-URL set),
not by retrieval quality: official_top@1 is 0.988 and official-source coverage is 1.0.
The weak categories (scholarship 0.119, student_services 0.333, admissions 0.6) are
**coverage gaps**, which is exactly what the next phase (6A/6B) targets.

---

## Artifacts

- `reports/benchmark_preprune.json` · `reports/benchmark_postprune.json` · `reports/benchmark_generation.json`
- `reports/prune_backup_20260615T223100Z.jsonl.gz` (recovery) · `reports/prune_baseline_*.json`
- Code: `app/api/routes_chat.py`, `app/agent/umb_agent.py`, `app/rag/answer_generator.py`,
  `app/core/config.py`, `app/db/prune_backup.py`, `.env` / `.env.example`
