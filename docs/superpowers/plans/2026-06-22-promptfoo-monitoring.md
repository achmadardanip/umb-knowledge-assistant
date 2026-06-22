# Promptfoo Self-Hosted RAG Monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a nightly, self-hosted Promptfoo RAG monitor that grades the real `/chat` endpoint (faithfulness + relevance + official-source) with a local Ollama judge and shows results in a web UI engineers browse — replacing the manual Excel report.

**Architecture:** A small `/chat` addition exposes retrieved context; a Promptfoo custom provider calls `/chat`; a new monitoring config applies model-graded RAG assertions with an Ollama grader; two docker-compose services (a self-hosted Promptfoo server + a nightly cron scheduler) run the eval and store/serve history.

**Tech Stack:** FastAPI (Python 3.12), Promptfoo (Node), Ollama (`qwen2.5:7b-instruct`), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-06-22-promptfoo-monitoring-selfhosted-design.md`

**Environment for backend commands:**
```bash
cd backend
export LOCAL_POSTGRES_MODE=true
export LOCAL_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/umb
# python: .venv/bin/python ; tests: .venv/bin/pytest
```

> **Spec reconciliation (read once):** The spec's "answer-relevance" is realized here via
> Promptfoo's `llm-rubric` (LLM-only, graded by Ollama) instead of the built-in
> `answer-relevance` assertion, because the latter needs an embeddings provider (extra
> Ollama model). This keeps the monitor fully local with no new model. True
> `answer-relevance` can be added later by configuring an Ollama embeddings provider.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/api/routes_chat.py` | + `include_retrieved_context` field + `_retrieved_context_payload` helper wired into the main return |
| `backend/app/api/tests/test_retrieved_context_payload.py` | unit test for the helper |
| `evaluation/promptfoo/rag_chat_provider.py` | Promptfoo provider that calls `/chat`, returns answer + context + sources |
| `evaluation/promptfoo/tests/test_rag_chat_provider.py` | provider shaping tests (mocked HTTP) |
| `evaluation/promptfoo/scenarios.csv` | curated, engineer-extendable scenarios |
| `evaluation/promptfoo/promptfooconfig.monitoring.yaml` | RAG assertions + Ollama grader + sharing target |
| `evaluation/promptfoo/tests/test_monitoring_config.py` | config + CSV validity test |
| `evaluation/promptfoo/scheduler/Dockerfile` | node + python + requests + promptfoo + cron |
| `evaluation/promptfoo/scheduler/crontab` | nightly schedule |
| `evaluation/promptfoo/scheduler/run-eval.sh` | entrypoint: `promptfoo eval --share` |
| `docker-compose.local.yml` | + `promptfoo-server`, `promptfoo-scheduler`, `promptfoo_data` volume |
| `evaluation/promptfoo/MONITORING.md` | engineer docs: view + add scenarios |

The existing `promptfooconfig.yaml`, `provider.py`, `promptfoo_runner` are **untouched**.

---

## Task 1: `/chat` exposes retrieved context (opt-in)

**Files:**
- Modify: `backend/app/api/routes_chat.py` (ChatRequest ~line 52; main return ~line 892)
- Test: `backend/app/api/tests/test_retrieved_context_payload.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/app/api/tests/test_retrieved_context_payload.py
from app.api.routes_chat import _retrieved_context_payload


def test_payload_empty_when_disabled():
    ctx = [{"chunk_text": "a"}, {"chunk_text": "b"}]
    assert _retrieved_context_payload(ctx, False) == {}


def test_payload_lists_chunks_when_enabled():
    ctx = [{"chunk_text": "a"}, {"chunk_text": "b"}, {"other": "x"}]
    out = _retrieved_context_payload(ctx, True)
    assert out["retrieved_context"] == ["a", "b", ""]
    assert out["retrieved_context_joined"] == "a\n\nb\n\n"


def test_payload_truncates_join():
    ctx = [{"chunk_text": "x" * 9000}]
    out = _retrieved_context_payload(ctx, True)
    assert len(out["retrieved_context_joined"]) == 8000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest app/api/tests/test_retrieved_context_payload.py -v`
Expected: FAIL — `ImportError: cannot import name '_retrieved_context_payload'`

- [ ] **Step 3: Add the field and helper, wire into the return**

In `ChatRequest` (the `class ChatRequest(BaseModel)` block, after the `audience` field at ~line 71), add:

```python
    include_retrieved_context: bool = False
```

Add this helper near the other module-level helpers (e.g. after `_with_audience`):

```python
def _retrieved_context_payload(contexts: list[dict], include: bool) -> dict:
    """Eval-only: expose retrieved chunk texts so Promptfoo can grade faithfulness."""
    if not include:
        return {}
    chunks = [(c.get("chunk_text") or "") for c in contexts]
    return {
        "retrieved_context": chunks,
        "retrieved_context_joined": "\n\n".join(chunks)[:8000],
    }
```

In the main success return inside `process_chat` (the `return { "session_id": ... }` at
~line 892), add this entry just before the closing `}` (after `retrieval_warnings`):

```python
        **_retrieved_context_payload(contexts, payload.include_retrieved_context),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest app/api/tests/test_retrieved_context_payload.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Confirm the app still imports**

Run: `.venv/bin/python -c "import app.main; print('import OK')"`
Expected: `import OK`

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_chat.py backend/app/api/tests/test_retrieved_context_payload.py
git commit -m "feat(chat): opt-in include_retrieved_context for eval"
```

---

## Task 2: Promptfoo provider that calls `/chat`

**Files:**
- Create: `evaluation/promptfoo/rag_chat_provider.py`
- Test: `evaluation/promptfoo/tests/test_rag_chat_provider.py`

- [ ] **Step 1: Write the failing test**

```python
# evaluation/promptfoo/tests/test_rag_chat_provider.py
import sys, types, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rag_chat_provider as p


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_success_shapes_output_and_metadata(monkeypatch):
    payload = {"answer": "Jawaban X", "not_found": False,
               "sources": [{"hostname": "pmb.mercubuana.ac.id"}],
               "retrieved_context": ["chunk a", "chunk b"]}
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: FakeResp(payload))
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert out["output"] == "Jawaban X"
    assert out["metadata"]["context"] == "chunk a\n\nchunk b"
    assert out["metadata"]["official_source"] is True
    assert out["metadata"]["not_found"] is False


def test_non_official_source_flagged(monkeypatch):
    payload = {"answer": "Y", "sources": [{"hostname": "wikipedia.org"}],
               "retrieved_context": ["c"]}
    monkeypatch.setattr(p.requests, "post", lambda *a, **k: FakeResp(payload))
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert out["metadata"]["official_source"] is False


def test_http_error_returns_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(p.requests, "post", boom)
    out = p.call_api("q", {}, {"vars": {"query": "q"}})
    assert "error" in out and "connection refused" in out["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: from `evaluation/promptfoo/`, `/Users/ardan/Developer/umb-knowledge-assistant/backend/.venv/bin/pytest tests/test_rag_chat_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rag_chat_provider'`

- [ ] **Step 3: Implement the provider**

```python
# evaluation/promptfoo/rag_chat_provider.py
"""Promptfoo provider — calls the real UMB /chat endpoint for RAG monitoring.

Returns the generated answer as `output` plus the retrieved context, citation
sources, and an official-source flag in `metadata`, so Promptfoo can grade
context-faithfulness and check official sourcing against the live chatbot.
"""
from __future__ import annotations

import os

import requests

_BASE = os.getenv("UMB_CHAT_BASE_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = int(os.getenv("UMB_CHAT_TIMEOUT", "240"))
_OFFICIAL_SUFFIX = os.getenv("UMB_OFFICIAL_DOMAIN", "mercubuana.ac.id")


def call_api(prompt, options, context):  # promptfoo python provider entrypoint
    query = (context or {}).get("vars", {}).get("query") or prompt
    try:
        resp = requests.post(
            f"{_BASE}/chat",
            json={"question": query, "include_retrieved_context": True},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network/timeout/5xx -> failed test, never crash the run
        return {"error": f"chat request failed: {exc}"}

    chunks = data.get("retrieved_context") or []
    sources = data.get("sources") or []
    hosts = [(s.get("hostname") or "").lower() for s in sources if s.get("hostname")]
    official = bool(hosts) and all(h == _OFFICIAL_SUFFIX or h.endswith("." + _OFFICIAL_SUFFIX) for h in hosts)
    return {
        "output": data.get("answer") or "",
        "metadata": {
            "context": "\n\n".join(chunks)[:8000],
            "sources": sources,
            "official_source": official,
            "not_found": bool(data.get("not_found")),
        },
    }
```

Also create an empty `evaluation/promptfoo/tests/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: from `evaluation/promptfoo/`, `/Users/ardan/Developer/umb-knowledge-assistant/backend/.venv/bin/pytest tests/test_rag_chat_provider.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add evaluation/promptfoo/rag_chat_provider.py evaluation/promptfoo/tests/
git commit -m "feat(monitoring): promptfoo provider calling real /chat"
```

---

## Task 3: Curated scenarios CSV

**Files:**
- Create: `evaluation/promptfoo/scenarios.csv`

- [ ] **Step 1: Create the CSV (seed across intents; engineers append rows)**

```csv
query,intent
Apa saja syarat pendaftaran mahasiswa baru di UMB?,admissions
Siapa dekan Fakultas Ilmu Komputer UMB?,faculty
Siapa dekan Fakultas Psikologi Universitas Mercu Buana?,faculty
Berapa biaya kuliah program studi Teknik Informatika di UMB?,tuition
Bagaimana cara mendaftar beasiswa KIP Kuliah di UMB?,scholarship
Bagaimana mahasiswa Teknik Sipil mengisi KRS di SIA?,sia
Bagaimana jika lupa password SSO Universitas Mercu Buana?,sso
Apa saja program studi di Fakultas Ekonomi dan Bisnis?,study_program
Di mana saja lokasi kampus Universitas Mercu Buana?,campus
Apa akreditasi program studi Sistem Informasi UMB?,study_program
Bagaimana cara menghubungi Biro Administrasi Akademik (BAA) UMB?,student_services
Apa saja layanan perpustakaan digital UMB?,library
```

> Format: each row is one scenario; `query` is the question, `intent` is a label var
> used for filtering in the UI. The config's default assertions apply to every row.
> Optional per-row override: add an `__expected` column, e.g. `llm-rubric: must mention biaya`.

- [ ] **Step 2: Verify it parses (12 data rows, 2 columns)**

Run:
```bash
/Users/ardan/Developer/umb-knowledge-assistant/backend/.venv/bin/python -c "import csv; r=list(csv.DictReader(open('evaluation/promptfoo/scenarios.csv'))); print(len(r), sorted(r[0].keys()))"
```
Expected: `12 ['intent', 'query']`

- [ ] **Step 3: Commit**

```bash
git add evaluation/promptfoo/scenarios.csv
git commit -m "feat(monitoring): seed curated scenarios.csv"
```

---

## Task 4: Monitoring config

**Files:**
- Create: `evaluation/promptfoo/promptfooconfig.monitoring.yaml`
- Test: `evaluation/promptfoo/tests/test_monitoring_config.py`

- [ ] **Step 1: Write the failing test**

```python
# evaluation/promptfoo/tests/test_monitoring_config.py
from pathlib import Path
import yaml

CFG = Path(__file__).resolve().parents[1] / "promptfooconfig.monitoring.yaml"


def test_config_is_valid_yaml_with_required_keys():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["providers"][0]["id"] == "file://rag_chat_provider.py"
    assert cfg["defaultTest"]["options"]["provider"].startswith("ollama:")
    types = [a["type"] for a in cfg["defaultTest"]["assert"]]
    assert "context-faithfulness" in types
    assert "llm-rubric" in types
    assert "scenarios.csv" in "".join(str(t) for t in cfg["tests"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: from `evaluation/promptfoo/`, `/Users/ardan/Developer/umb-knowledge-assistant/backend/.venv/bin/pytest tests/test_monitoring_config.py -v`
Expected: FAIL — file not found / KeyError

- [ ] **Step 3: Create the config**

```yaml
# evaluation/promptfoo/promptfooconfig.monitoring.yaml
# Nightly RAG monitoring against the real /chat endpoint. Graded by local Ollama.
# Run by the promptfoo-scheduler container; results pushed to promptfoo-server.
description: UMB Chatbot — RAG monitoring (faithfulness/relevance) vs real /chat

providers:
  - id: file://rag_chat_provider.py
    label: umb-chat-endpoint

prompts:
  - "{{query}}"

defaultTest:
  options:
    provider: ollama:chat:qwen2.5:7b-instruct   # local judge (grader), temperature via Ollama
  assert:
    - type: context-faithfulness        # hallucination signal: answer vs retrieved context
      contextTransform: metadata.context
      threshold: 0.7
    - type: llm-rubric                   # relevance (LLM-only; see plan spec-reconciliation note)
      value: "The ANSWER directly and helpfully addresses the QUESTION (ignore factual correctness; judge relevance only). Pass if relevant."
    - type: javascript                   # official-source check from provider metadata
      value: |
        const m = (context && context.metadata) || {};
        if (m.not_found) return { pass: true, score: 1, reason: 'refusal: no sources expected' };
        return m.official_source
          ? { pass: true, score: 1, reason: 'official sources' }
          : { pass: false, score: 0, reason: 'non-official or empty sources' };

tests:
  - file://scenarios.csv
  - file://datasets/rag_golden.json

# Sharing target is set via the PROMPTFOO_REMOTE_API_BASE_URL / PROMPTFOO_REMOTE_APP_BASE_URL
# environment variables (set by the scheduler container and the smoke command), which
# `promptfoo eval --share` reads natively. No in-file sharing block (avoids literal ${VAR}).
outputPath: reports/promptfoo_monitoring_latest.json
```

- [ ] **Step 4: Run test to verify it passes**

Run: from `evaluation/promptfoo/`, `/Users/ardan/Developer/umb-knowledge-assistant/backend/.venv/bin/pytest tests/test_monitoring_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evaluation/promptfoo/promptfooconfig.monitoring.yaml evaluation/promptfoo/tests/test_monitoring_config.py
git commit -m "feat(monitoring): promptfoo config with RAG assertions + Ollama grader"
```

---

## Task 5: Scheduler image (cron + promptfoo)

**Files:**
- Create: `evaluation/promptfoo/scheduler/Dockerfile`
- Create: `evaluation/promptfoo/scheduler/crontab`
- Create: `evaluation/promptfoo/scheduler/run-eval.sh`

- [ ] **Step 1: Create `run-eval.sh`**

```bash
#!/usr/bin/env bash
# Run the nightly RAG monitoring eval and push results to the self-hosted server.
set -uo pipefail
cd /work/evaluation/promptfoo
echo "[$(date -u +%FT%TZ)] starting promptfoo monitoring eval"
npx --yes promptfoo@0.121.17 eval \
  -c promptfooconfig.monitoring.yaml \
  --share --no-progress-bar
echo "[$(date -u +%FT%TZ)] eval finished (exit $?)"
```

- [ ] **Step 2: Create `crontab`**

```cron
# nightly at 02:00; logs go to the container stdout via /proc/1/fd/1
0 2 * * * root /usr/local/bin/run-eval.sh > /proc/1/fd/1 2>/proc/1/fd/2
```

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
# evaluation/promptfoo/scheduler/Dockerfile
FROM node:20-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-requests cron ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Pre-cache the pinned promptfoo CLI
RUN npx --yes promptfoo@0.121.17 --version || true

COPY run-eval.sh /usr/local/bin/run-eval.sh
COPY crontab /etc/cron.d/promptfoo-eval
RUN chmod +x /usr/local/bin/run-eval.sh \
 && chmod 0644 /etc/cron.d/promptfoo-eval \
 && crontab /etc/cron.d/promptfoo-eval

# The repo is mounted at /work (see docker-compose). cron runs in the foreground.
WORKDIR /work/evaluation/promptfoo
CMD ["cron", "-f"]
```

> `python3-requests` satisfies the provider's only dependency. The repo is bind-mounted at
> `/work` by compose so the config/provider/scenarios are available without rebuilds.

- [ ] **Step 4: Verify the image builds**

Run: `docker build -t umb-promptfoo-scheduler evaluation/promptfoo/scheduler`
Expected: build completes; final line `naming to ... umb-promptfoo-scheduler`.

- [ ] **Step 5: Commit**

```bash
git add evaluation/promptfoo/scheduler/
git commit -m "feat(monitoring): scheduler image (cron + promptfoo)"
```

---

## Task 6: Docker Compose services

**Files:**
- Modify: `docker-compose.local.yml` (add two services + a named volume)

- [ ] **Step 1: Add the services**

Under the `services:` block, add:

```yaml
  promptfoo-server:
    image: ghcr.io/promptfoo/promptfoo:latest
    container_name: umb-promptfoo-server
    ports:
      - "3000:3000"
    volumes:
      - promptfoo_data:/home/promptfoo/.promptfoo
    restart: unless-stopped

  promptfoo-scheduler:
    build: ./evaluation/promptfoo/scheduler
    container_name: umb-promptfoo-scheduler
    depends_on:
      - promptfoo-server
    environment:
      PROMPTFOO_REMOTE_API_BASE_URL: http://promptfoo-server:3000
      PROMPTFOO_REMOTE_APP_BASE_URL: http://promptfoo-server:3000
      UMB_CHAT_BASE_URL: http://host.docker.internal:8000
      OLLAMA_BASE_URL: http://host.docker.internal:11434
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./:/work:ro
    restart: unless-stopped
```

> `UMB_CHAT_BASE_URL` points at the host (`host.docker.internal:8000`) because the backend
> in this repo is typically run via uvicorn on the host. If you instead run the backend as
> a compose service named `backend`, change it to `http://backend:8000` and add `backend`
> to `depends_on`.

Add the named volume under the top-level `volumes:` block (it already contains
`umb_local_pgdata`):

```yaml
  promptfoo_data:
```

- [ ] **Step 2: Validate compose config**

Run: `docker compose -f docker-compose.local.yml config >/dev/null && echo "compose OK"`
Expected: `compose OK` (no YAML/schema errors).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.local.yml
git commit -m "feat(monitoring): promptfoo server + scheduler compose services"
```

---

## Task 7: Live smoke (controller-run)

**Files:** none (verification only). Requires backend + Ollama running and KB restored.

- [ ] **Step 1: Start the self-hosted server**

Run: `docker compose -f docker-compose.local.yml up -d promptfoo-server`
Then check: `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000` → expect `200`.

- [ ] **Step 2: Run a 2-scenario eval from the host against the live stack**

Create a tiny temp config limiting tests, then run eval pointing at the local server:
```bash
cd evaluation/promptfoo
PROMPTFOO_REMOTE_API_BASE_URL=http://localhost:3000 \
PROMPTFOO_REMOTE_APP_BASE_URL=http://localhost:3000 \
UMB_CHAT_BASE_URL=http://localhost:8000 \
npx --yes promptfoo@0.121.17 eval -c promptfooconfig.monitoring.yaml \
  --filter-first-n 2 --share --no-progress-bar
```
Expected: eval completes; prints per-assertion pass/fail for 2 scenarios and a shared URL.

- [ ] **Step 3: Verify the `contextTransform` + assertions actually fired**

In the eval output, confirm `context-faithfulness` produced a numeric score (not an error
about missing context) and the `javascript` official-source assertion ran. If
`context-faithfulness` errors with "missing context", adjust the `contextTransform`
expression in `promptfooconfig.monitoring.yaml` (try `output.metadata.context` or expose
context via a var) and re-run this step until it scores. Commit any fix:
```bash
git add evaluation/promptfoo/promptfooconfig.monitoring.yaml
git commit -m "fix(monitoring): correct contextTransform for faithfulness"
```

- [ ] **Step 4: Verify results appear in the server UI**

Open `http://localhost:3000` in a browser → the eval run is listed with the 2 scenarios,
faithfulness/relevance/official-source columns, and per-row detail. (Confirms the
engineer-facing view works.)

---

## Task 8: Engineer docs + finalize

**Files:**
- Create: `evaluation/promptfoo/MONITORING.md`
- Modify: `README.md` (one line under Promptfoo Evaluation pointing to MONITORING.md)

- [ ] **Step 1: Write `evaluation/promptfoo/MONITORING.md`**

```markdown
# RAG Monitoring (self-hosted Promptfoo)

Automated nightly evaluation of the real `/chat` endpoint — faithfulness +
relevance + official-source — graded by the local Ollama model. Results are
browsable in a self-hosted Promptfoo UI. This replaces the manual Excel report.

## View results
Open the server UI: **http://<host>:3000** — pick the latest run; filter by `intent`;
compare across nights. No manual input needed.

## Add a test scenario
Append a row to `evaluation/promptfoo/scenarios.csv`:
```
query,intent
Apa syarat wisuda di UMB?,academic_regulations
```
Commit it; the next nightly run includes it automatically. Optional per-row check: add an
`__expected` column (e.g. `llm-rubric: harus menyebut biaya`).

## Run / operate
- Start: `docker compose -f docker-compose.local.yml up -d promptfoo-server promptfoo-scheduler`
- The scheduler runs nightly at 02:00 (`evaluation/promptfoo/scheduler/crontab`).
- Manual run from the host:
  `cd evaluation/promptfoo && UMB_CHAT_BASE_URL=http://localhost:8000 npx promptfoo@0.121.17 eval -c promptfooconfig.monitoring.yaml --share`
- Requires the backend (`/chat`) + Ollama + restored KB to be up.

## Caveat
The judge is the local `qwen2.5:7b-instruct` — scores are a **signal for human review**,
not absolute truth. It's report-only and does not gate releases. The deterministic CI gate
(`promptfoo_runner`) and the in-app `/eval` dashboard are unchanged.
```

- [ ] **Step 2: Add a README pointer**

Under `## Promptfoo Evaluation` in `README.md`, append:

```markdown
### RAG Monitoring (self-hosted, nightly)
Automated nightly model-graded eval of the real `/chat` (faithfulness + relevance) in a
self-hosted Promptfoo UI — see [evaluation/promptfoo/MONITORING.md](evaluation/promptfoo/MONITORING.md).
```

- [ ] **Step 3: Run the full new unit suite (no regressions)**

Run: from `backend/`, `.venv/bin/pytest app/api/tests/test_retrieved_context_payload.py -v`
and from `evaluation/promptfoo/`, `.../backend/.venv/bin/pytest tests -v`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add evaluation/promptfoo/MONITORING.md README.md
git commit -m "docs(monitoring): engineer guide for self-hosted RAG monitoring"
```

---

## Self-Review Notes

- **Spec coverage:** /chat context field → Task 1; provider calling /chat → Task 2;
  scenarios CSV (+ reuse golden json in config) → Tasks 3-4; config with faithfulness +
  relevance(llm-rubric) + official-source + Ollama grader → Task 4; scheduler image → Task 5;
  compose server+scheduler+volume → Task 6; smoke incl. contextTransform verification →
  Task 7; engineer docs/coexistence → Task 8.
- **Documented deviation:** spec "answer-relevance" → `llm-rubric` (local, no embeddings model);
  noted at top + Task 4.
- **Verify-in-smoke (integration unknowns):** exact `contextTransform` expression and JS
  assertion access to `context.metadata` are confirmed/adjusted in Task 7 (the one place
  live promptfoo behavior is exercised) — not left as silent assumptions.
- **Type/name consistency:** `_retrieved_context_payload(contexts, include)`,
  response keys `retrieved_context` / `retrieved_context_joined`, and provider
  `metadata.context` / `metadata.official_source` / `metadata.not_found` are used
  consistently across Tasks 1, 2, 4.
- **CI note:** the nightly LLM eval cannot run on GitHub-hosted runners (no Ollama/KB); it
  runs only on the host via the scheduler container — consistent with the spec.
