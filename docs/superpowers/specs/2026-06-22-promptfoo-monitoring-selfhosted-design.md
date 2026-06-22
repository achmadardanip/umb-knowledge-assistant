# Promptfoo Self-Hosted RAG Monitoring — Design

**Date:** 2026-06-22
**Status:** Approved (pending written-spec review)
**Owner:** Achmad Ardani Prasha

## 1. Problem & Goal

The current QA artifact is a **manually built Excel report** — a one-off snapshot that
someone has to regenerate and hand around. We want evaluation of the chatbot across **all
test scenarios** to run **automatically** and be **viewable by engineers in a UI**, with no
manual spreadsheet step.

**Goal:** Stand up Promptfoo as an automated, self-hosted **RAG monitoring** tool that:
- nightly runs model-graded RAG evaluation against the **real `/chat` endpoint**,
- grades **faithfulness** (the P0 hallucination issue) and **answer-relevance** with a **local
  Ollama judge**, plus an official-source check,
- stores run **history** and exposes a **web UI** (self-hosted Promptfoo server) engineers
  browse without any manual input,
- lets engineers add scenarios by editing a **CSV** (no code, no Excel).

This is the engineer-facing successor to the manual Excel report.

## 2. Decisions (captured in brainstorming)

1. **Eval target:** the real `/chat` endpoint, end-to-end (representative of what users see).
2. **UI hosting:** self-hosted Promptfoo Docker server.
3. **Context exposure:** add an opt-in eval field to `/chat` so the response includes the
   retrieved context text (needed for `context-faithfulness`).
4. **Scenarios:** both a curated **CSV** (engineers extend) and the existing **generated
   golden slice** JSON.
5. **Scheduler:** Docker Compose — a self-hosted server service + a scheduler (cron) service.
6. **Cadence:** nightly.
7. **Judge/grader:** local Ollama `qwen2.5:7b-instruct`, temperature 0 (env-configurable).

## 3. Scope

### In scope
- Opt-in `include_retrieved_context` field on `/chat`.
- A Promptfoo custom provider that calls `/chat` and returns answer + context + sources.
- A new monitoring promptfoo config with model-graded RAG assertions + Ollama grader.
- A curated `scenarios.csv` (seeded ~40–60 across intents) + reuse of `datasets/rag_golden.json`.
- Two Docker Compose services: `promptfoo-server` and `promptfoo-scheduler` (nightly cron).
- Docs for engineers (how to view, how to add scenarios).

### Out of scope
- `context-recall` (needs per-question ground-truth document labels) — deferred (YAGNI).
- Multi-team RBAC / SSO (that is Promptfoo Enterprise). OSS single-host viewer is sufficient.
- Replacing the in-app `/eval` dashboard or the deterministic CI gate — both stay (see §8).
- Cloud grader. Local Ollama only (model id is env-swappable).

## 4. Architecture

```
docker compose (extends docker-compose.local.yml)

  [backend]  POST /chat (+ include_retrieved_context=true)
       │  answers via Ollama (host :11434)
       ▼
  [promptfoo-scheduler]  cron nightly 02:00
     runs: promptfoo eval -c promptfooconfig.monitoring.yaml --share
       • provider rag_chat_provider.py --POST /chat--> {output: answer,
                                          metadata:{context, sources, not_found}}
       • grader: ollama:chat:qwen2.5:7b-instruct  (temp 0)
       • assertions: context-faithfulness, answer-relevance, official-source
       • tests: scenarios.csv (+) datasets/rag_golden.json
       │  push results (--share, PROMPTFOO_REMOTE_*_BASE_URL)
       ▼
  [promptfoo-server]  ghcr.io/promptfoo/promptfoo:latest  :3000
       (web UI + SQLite history, persisted on a named volume)
       ▲
  Engineers --> http://<host>:3000  (run list, per-scenario pass/fail,
       faithfulness/relevance, history, cross-run compare, filter by intent)
```

## 5. Components & File Layout

```
backend/app/api/routes_chat.py        # EDIT: + optional include_retrieved_context -> response.retrieved_context
backend/app/api/tests/test_chat_include_context.py   # NEW: field on/off behaviour
evaluation/promptfoo/
  rag_chat_provider.py                # NEW: calls /chat, returns answer + context + sources
  promptfooconfig.monitoring.yaml     # NEW: RAG assertions + Ollama grader + sharing target
  scenarios.csv                       # NEW: curated, engineer-extendable scenarios (seeded)
  tests/test_rag_chat_provider.py     # NEW: provider response shaping (mocked HTTP)
  scheduler/Dockerfile                # NEW: node + python + requests + promptfoo + cron
  scheduler/crontab                   # NEW: nightly schedule
  scheduler/run-eval.sh               # NEW: entrypoint that runs `promptfoo eval --share`
  README.md                           # NEW/EDIT: how to view + add scenarios
docker-compose.local.yml              # EDIT: + promptfoo-server, promptfoo-scheduler, volume
```

The existing deterministic `promptfooconfig.yaml`, `provider.py`, and `promptfoo_runner`
are **left untouched**.

## 6. Component Detail

### 6.1 `/chat` eval field (backend)
- Add `include_retrieved_context: bool = False` to the chat request model.
- When true, the response includes `retrieved_context: list[str]` (the `chunk_text` of the
  contexts used) and `retrieved_context_joined: str` (chunks joined, truncated ~8000 chars).
- Default false → **no change** to existing behaviour/clients (backward-compatible).
- Touches only the final answer return path in `routes_chat.py`.

### 6.2 `rag_chat_provider.py`
- Promptfoo Python provider entrypoint `call_api(prompt, options, context)`.
- Reads `query` from `context.vars`; POSTs to `${UMB_CHAT_BASE_URL}/chat` with
  `{question, include_retrieved_context: true}`.
- Returns `{ "output": answer, "metadata": { "context": joined_context, "sources": [...],
  "not_found": bool } }`.
- On HTTP error/timeout → returns `{ "error": "<msg>" }` so Promptfoo records a failed test
  (never crashes the run).
- Only dependency: `requests` (HTTP). No backend imports → runs in a light container.

### 6.3 `promptfooconfig.monitoring.yaml`
- `providers: [file://rag_chat_provider.py]`.
- `defaultTest.options.provider: ollama:chat:qwen2.5:7b-instruct` (the grader/judge).
- Assertions (from the promptfoo RAG guide):
  - `context-faithfulness` with `contextTransform` to pull context from the provider's
    `metadata.context` (exact transform expression verified against the installed promptfoo
    version during the smoke test; fallback: expose context via a test var). Threshold 0.7.
  - `answer-relevance`, threshold 0.6.
  - a `javascript` official-source assertion over `output`/`metadata.sources` (port the
    existing host-authority check).
- `tests: [file://scenarios.csv, file://datasets/rag_golden.json]`.
- `sharing.apiBaseUrl` / `appBaseUrl` → `http://promptfoo-server:3000` (also settable via
  `PROMPTFOO_REMOTE_API_BASE_URL` / `PROMPTFOO_REMOTE_APP_BASE_URL`).

### 6.4 Scenarios
- `scenarios.csv` columns: `query` (the question), `intent` (var, for filtering/labeling),
  optional `__expected` (per-row assertion, e.g. `llm-rubric: ...`). Default assertions apply
  to every row, so a minimal row is just a `query`. Seeded ~40–60 across all intents
  (faculties, programs, admissions, tuition, scholarships, SIA, SSO, services, library,
  calendar, regulations, lecturers).
- `datasets/rag_golden.json` reused as-is for broad generated coverage.
- Adding a scenario = add a CSV row + commit. Next nightly run includes it automatically.

### 6.5 Docker services
- **`promptfoo-server`**: `ghcr.io/promptfoo/promptfoo:latest`, port `3000:3000`, volume
  `promptfoo_data:/home/promptfoo/.promptfoo`, `restart: unless-stopped`.
- **`promptfoo-scheduler`**: built from `evaluation/promptfoo/scheduler/Dockerfile`
  (node 20 + python3 + `requests` + `promptfoo` + cron). Env: `PROMPTFOO_REMOTE_*_BASE_URL`
  → server, `UMB_CHAT_BASE_URL=http://backend:8000`,
  `OLLAMA_BASE_URL=http://host.docker.internal:11434`. `extra_hosts: ["host.docker.internal:host-gateway"]`
  for Linux portability. Cron `0 2 * * *` runs `run-eval.sh` → `promptfoo eval -c ... --share`.
- Named volume `promptfoo_data` added to the compose `volumes:` block.

## 7. Data Flow (one nightly run)

1. Cron fires `run-eval.sh` in the scheduler container.
2. `promptfoo eval` loads scenarios (CSV + JSON), and for each: calls
   `rag_chat_provider` → `POST backend:8000/chat` (include_retrieved_context) → answer + context.
3. For each test, the grader (Ollama) scores `context-faithfulness` + `answer-relevance`;
   the JS assertion checks official source.
4. `--share` pushes the completed eval to `promptfoo-server` (SQLite, persisted).
5. Engineers open `http://<host>:3000` and browse the run, history, and per-intent results.

## 8. Coexistence (nothing removed)

| Tool | Role after this change |
|---|---|
| Deterministic CI gate (`promptfoo_runner`) | Unchanged — fast no-LLM regression gate on PRs. |
| In-app `/eval` dashboard | Stays — on-demand / live single-run view inside the app. |
| **This monitoring config** | **New** — scheduled, engineer-facing, model-graded report in the self-hosted UI. Replaces the manual Excel. |

## 9. Error Handling

| Failure | Behaviour |
|---|---|
| Backend or Ollama down at run time | Eval run fails/partial; server keeps showing the last good run; scheduler retries next night. |
| `/chat` timeout or 500 on a scenario | Provider returns `{error}` → Promptfoo marks that test failed (run continues). |
| Grader (Ollama) malformed output | Promptfoo records the assertion as errored for that row; other rows continue. |
| Long runtime (~30–90 min for 40–60 scenarios) | Acceptable — nightly cadence; not on a request path. |
| `host.docker.internal` unavailable (Linux) | `extra_hosts: host-gateway` mapping makes Ollama reachable. |

## 10. Testing Strategy (TDD)

- **Unit (no live services):**
  - `test_chat_include_context` — `/chat` includes `retrieved_context` when the flag is true,
    omits it when false/absent (mock the retrieval+answer path).
  - `test_rag_chat_provider` — provider returns correct `{output, metadata}` on success,
    `not_found` passthrough, and `{error}` on HTTP failure (mock `requests`).
- **Smoke (live stack):** `promptfoo eval` on a 2-scenario subset against the running
  backend + Ollama; confirm the run appears in the `:3000` UI with faithfulness/relevance
  scores. This is also where the exact `contextTransform` expression is verified.
- **Ops check:** `docker compose up promptfoo-server promptfoo-scheduler` healthy; volume
  persists history across restart.

## 11. Risks & Mitigations

- **Local 7B judge is noisy** → temperature 0, report-only (monitoring, not gating); per-row
  reasons visible in the UI for human audit; same caveat documented for engineers.
- **Promptfoo `contextTransform` API specifics vary by version** → pin the promptfoo version
  in the scheduler image; verify the transform in the smoke test before relying on nightly.
- **OSS self-host limits (single host, SQLite, no RBAC)** → acceptable for internal QA→eng
  use; volume-backed persistence; revisit Enterprise only if multi-team access is needed.
- **Runtime drift / flaky refusals** → cadence nightly; trends (not single runs) drive
  decisions; refusal rate is itself a tracked signal.

## 12. Defaults / Env

- Grader (set in `promptfooconfig.monitoring.yaml` → `defaultTest.options.provider`):
  `ollama:chat:qwen2.5:7b-instruct` (swap the config value / use a var to change judge)
- `UMB_CHAT_BASE_URL=http://backend:8000`
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`
- `PROMPTFOO_REMOTE_API_BASE_URL` / `PROMPTFOO_REMOTE_APP_BASE_URL=http://promptfoo-server:3000`
- Cron schedule: `0 2 * * *` (nightly 02:00)
- Faithfulness threshold 0.7 · answer-relevance threshold 0.6 (report-only; tunable)
