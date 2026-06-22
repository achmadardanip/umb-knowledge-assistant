# Promptfoo-style RAG Evaluation with Live In-App Dashboard — Design

**Date:** 2026-06-22
**Status:** Approved (pending written-spec review)
**Owner:** Achmad Ardani Prasha

## 1. Problem & Goal

The UMB Knowledge Assistant already has strong **deterministic** evaluation: a 913-test
promptfoo gate (`app.evaluation.promptfoo_runner`), a retrieval benchmark
(`official_top` 0.998), and production certification. What it lacks — and what the
[promptfoo "Evaluate RAG" guide](https://www.promptfoo.dev/docs/guides/evaluate-rag/)
describes — is **model-graded evaluation of the generated answer against its retrieved
context**: faithfulness (groundedness) and answer-relevance.

The README explicitly records this gap: *"Full NLI groundedness certification is pending
a ≥4 GB GPU (lexical CPU gate active)."* An LLM-graded faithfulness check fills exactly
that hole using the already-running local model — no GPU/NLI dependency.

**Goal:** Add a faithfulness + answer-relevance evaluation over a curated golden slice,
graded by the local Ollama model, surfaced as a **real-time in-app dashboard** that shows
each question being graded live, with running aggregates and per-run history.

## 2. Scope

### In scope
- **Metrics:** faithfulness (primary) + answer-relevance (secondary). *Not* context
  relevance/recall — already covered by the retrieval benchmark (YAGNI).
- **Grader:** local Ollama (`qwen2.5:7b-instruct`), env-configurable model id, temperature 0.
- **Posture:** report-only / non-gating. Displayed and tracked, never blocks merges.
- **Dataset:** committed ~40-question stratified slice of `data/golden_dataset.jsonl`
  (authentic + answerable, spread across intents).
- **Surface:** live in-app dashboard page (`/eval`) in the existing Next.js app, fed by a
  custom Python runner that streams per-question results over SSE; results persisted in
  Postgres.

### Out of scope
- Context relevance/recall metrics.
- Cloud graders (grader model is env-configurable, but local is the only supported default).
- Promptfoo CLI as the live driver. The existing deterministic `promptfoo_runner`,
  `promptfooconfig.yaml`, and `provider.py` are **left untouched**.
- CI execution of the full LLM run (GH runners have no Ollama/KB) — CI does structural
  validation only.

## 3. Why a custom runner instead of promptfoo-native

Promptfoo's CLI produces a JSON report at the end of a run and has its own separate web
viewer; it does not stream per-question results into the app UI as it grades. The approved
requirement is a **live in-app dashboard**, so grading moves into a custom Python runner
that persists each result and emits a progress event the frontend streams. The *methodology*
(faithfulness + answer-relevance rubrics, local judge) is taken from the promptfoo guide;
only the driver differs.

## 4. Architecture

```
                 Next.js /eval page
                       │  fetch + ReadableStream reader (matches app/lib/api.ts)
                       ▼
   POST /eval/rag/runs ──► start background task ──► returns run_id
   GET  /eval/rag/runs/{id}/stream  (SSE, text/event-stream)
   GET  /eval/rag/runs , /eval/rag/runs/{id}      (history + hydrate)
                       │
                       ▼
          rag_eval_runner (FastAPI background task)
   for each golden question:
     HybridRetriever → context chunks
     generate_answer(...) → answer (+ not_found)
     rag_graders.grade_faithfulness(q, context, answer)   ← Ollama, temp 0
     rag_graders.grade_relevance(q, answer)               ← Ollama, temp 0
     persist RagEvalResult row + publish progress event (in-memory pub/sub)
                       │
                       ▼
          Postgres: rag_eval_runs, rag_eval_results
```

The runner runs **inside the backend process** (the LLM + embedder are already loaded
there). An in-memory pub/sub bridges the background task to SSE subscribers; persistence
makes the page resilient to refresh/reconnect.

## 5. Components & File Layout

New / edited files (existing eval gate untouched):

```
backend/app/evaluation/
  rag_eval_runner.py            # NEW  orchestration + background task + in-memory pub/sub
  rag_graders.py                # NEW  faithfulness + relevance rubrics, Ollama call, JSON parsing (pure)
  rag_golden_subset.py          # NEW  deterministic stratified sampler → evaluation/promptfoo/datasets/rag_golden.json
  tests/test_rag_golden_subset.py  # NEW  unit: count / stratification / determinism
  tests/test_rag_graders.py        # NEW  unit: parsing + scoring with MOCKED ollama client
backend/app/api/
  routes_rag_eval.py            # NEW  POST/GET runs + SSE stream; registered in main.py via include_router
backend/app/db/
  models.py                     # EDIT + RagEvalRun, RagEvalResult ORM models
backend/app/main.py             # EDIT app.include_router(routes_rag_eval.router)
evaluation/promptfoo/datasets/
  rag_golden.json               # NEW  committed ~40-Q eval slice
frontend/app/eval/
  page.tsx + components/*        # NEW  live dashboard (shadcn/ui + Tailwind + dark-mode tokens)
frontend/app/lib/api.ts         # EDIT + eval client + streaming hook (reuse getReader pattern)
reports/promptfoo_rag_latest.json  # NEW (gitignored) optional export of latest run
```

## 6. Data Model (Postgres)

**`rag_eval_runs`**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| status | text | `running` \| `completed` \| `failed` |
| started_at / finished_at | timestamptz | |
| dataset_version | text | from golden_dataset stats |
| grader_model | text | e.g. `qwen2.5:7b-instruct` |
| n_total / n_done | int | progress |
| agg_faithfulness / agg_relevance | float | running means over graded rows |
| n_not_found / n_grader_error | int | excluded-from-score counters |
| error | text null | set when status=failed |

**`rag_eval_results`**
| column | type | notes |
|---|---|---|
| id | uuid PK | |
| run_id | uuid FK → rag_eval_runs | indexed |
| question_id / question / intent | text | from golden slice |
| answer | text | generated answer |
| context | text | joined retrieved chunks (for audit/expand) |
| faithfulness_score | float null | null when not_found / grader_error |
| faithfulness_pass | bool null | score ≥ threshold |
| faithfulness_reason | text | judge rationale |
| relevance_score / relevance_pass / relevance_reason | float/bool/text | |
| not_found | bool | pipeline refusal |
| grader_error | bool | parse/LLM failure on this row |
| latency_ms | int | answer + grading wall time |
| created_at | timestamptz | |

Tables created via the existing ORM `bootstrap_local` path (`Base.metadata.create_all`,
checkfirst) — consistent with the other 24 tables; no separate migration framework.

## 7. API

All under a new `routes_rag_eval.router`.

- `POST /eval/rag/runs` → starts a run as a background task; returns `{run_id}`. Returns
  **409** if a run is already `running` (the local LLM is single-instance).
- `GET /eval/rag/runs` → list recent runs (id, status, aggregates, timestamps).
- `GET /eval/rag/runs/{id}` → run detail + all result rows (used to hydrate the page on
  load and after reconnect).
- `GET /eval/rag/runs/{id}/stream` → `StreamingResponse(..., media_type="text/event-stream")`
  using the existing `_sse(event, data)` helper. Event types:
  - `progress` `{n_done, n_total, agg_faithfulness, agg_relevance}`
  - `result` `{question_id, question, intent, faithfulness_score/pass, relevance_score/pass, not_found, grader_error, latency_ms}`
  - `done` `{run_id, status, aggregates}`
  - `error` `{message}`
  On subscribe, the endpoint first replays already-completed rows from the DB, then live
  events — so a mid-run refresh loses nothing.

## 8. Grading Rubrics (`rag_graders.py`)

Two pure functions; each builds a strict JSON-only prompt, calls Ollama (reusing the
project's existing local-LLM client/config), parses, and returns a dataclass.

- **`grade_faithfulness(question, context, answer) -> FaithfulnessVerdict`**
  Judge enumerates the answer's atomic claims and marks each `supported` / `unsupported`
  strictly against `context`. Returns `{score, supported[], unsupported[], reason}` where
  `score = supported / max(total,1)`. `pass = score >= FAITHFULNESS_THRESHOLD` (default 0.8).
- **`grade_relevance(question, answer) -> RelevanceVerdict`**
  `llm-rubric`-style: does the answer directly address the question? Returns `{score, reason}`,
  `pass = score >= RELEVANCE_THRESHOLD` (default 0.7). Chosen over promptfoo's embedding-based
  `answer-relevance` to avoid pulling an extra embedding model — keeps it fully local.
- **Refusals:** if pipeline returns `not_found`, skip faithfulness (no claims), set
  `not_found=True`; excluded from aggregates.
- **Robust parsing:** strip ``` fences, extract first `{...}` JSON object, one retry on
  failure, else `grader_error=True` and continue (row excluded from aggregates).
- Thresholds + grader model id read from env (with defaults) so they're tunable without
  code changes.

## 9. Frontend — `/eval` Live Dashboard

New page at `app/eval/page.tsx` (flat route, matching `app/dashboard` and `app/analytics`),
reusing shadcn/ui, Tailwind, and the dark-mode tokens already in the app; styled to match
`/dashboard`.

- **Header:** "Run evaluation" button (POST → run_id), grader-model + dataset-version
  badges, live status pill (`idle` / `running` / `completed` / `failed`).
- **Live progress:** progress bar `n_done/n_total`, two running-aggregate gauges
  (faithfulness, relevance), elapsed timer.
- **Streaming results table:** one row per question as graded — question, intent,
  faithfulness ✓/✗ + score, relevance ✓/✗, `not_found` / `grader_error` badges. Row
  expands to show generated answer, retrieved context, and judge reasons.
- **History:** recent runs list + a small faithfulness-over-runs trend line.
- **Transport:** reuses the `fetch` + `response.body.getReader()` streaming pattern from
  `app/lib/api.ts` (the same approach as `/chat/stream`). On mount / reconnect it calls
  `GET /eval/rag/runs/{id}` to hydrate, then resumes the stream.

## 10. Error Handling

| Failure | Behaviour |
|---|---|
| Ollama unreachable at start | run → `failed`, `error` set, SSE `error` emitted, UI shows banner |
| Answer generation error on a question | row recorded with `grader_error`, run continues |
| Grader JSON parse failure | one retry, then `grader_error=True`, row excluded from aggregates, run continues |
| SSE client disconnect | run keeps going (persisted); client reconnects + replays from DB |
| Second concurrent run | `POST` returns 409 |

## 11. Testing Strategy (TDD)

- **Unit (no real LLM):**
  - `test_rag_golden_subset` — deterministic sample (fixed seed), exact count, intent
    stratification, authentic+answerable filter.
  - `test_rag_graders` — JSON parsing across clean / fenced / malformed outputs; score &
    pass-threshold logic; refusal handling — all with a **mocked** Ollama client.
- **Integration smoke:** a 2-question live run against real Ollama validating the full path
  (DB rows written, SSE events emitted, page updates) before any full run.
- **Full run:** ~40-Q run; eyeball faithfulness distribution and per-row reasons.
- **Frontend:** component render + manual live-update verification against the running app.
- **CI:** structural validation only — golden slice well-formed + sampler unit test; the
  LLM run stays local. Never gates.

## 12. Risks & Mitigations

- **Local-model grading is noisy** → temperature 0, strict JSON rubric, report-only posture,
  show the judge's reason per row for human audit.
- **Long run time (~20–60 min)** → live streaming makes progress visible; single-run guard
  prevents overlap; runs are resumable via persistence.
- **Self-grading bias** (same model answers and grades) → acceptable for a report-only trend
  signal; grader model is env-swappable for deeper audits later.

## 13. Out-of-the-box Defaults

- `RAG_EVAL_GRADER_MODEL=qwen2.5:7b-instruct`
- `RAG_EVAL_FAITHFULNESS_THRESHOLD=0.8`
- `RAG_EVAL_RELEVANCE_THRESHOLD=0.7`
- `RAG_EVAL_GOLDEN_SIZE=40`
