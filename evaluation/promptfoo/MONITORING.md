# RAG Monitoring (self-hosted Promptfoo)

Automated nightly evaluation of the real `/chat` endpoint — **faithfulness**,
**relevance**, and **official-source** — graded by the local Ollama model
(`qwen2.5:7b-instruct`). Results are browsable in a self-hosted Promptfoo UI.
This replaces the manual Excel report.

## View results
Open the server UI: **http://<host>:3001** — pick the latest run; filter by `intent`;
compare across nights. No manual input needed.

## Add a test scenario
Append a row to `evaluation/promptfoo/scenarios.csv`:
```
query,intent
Apa syarat wisuda di UMB?,academic_regulations
```
Commit it; the next nightly run includes it automatically. Optional per-row check: add an
`__expected` column (e.g. `llm-rubric: harus menyebut biaya`).

## Broad coverage (golden_scenarios.csv)
`golden_scenarios.csv` is the broad generated coverage, derived from
`datasets/rag_golden.json`. Regenerate it when the golden slice changes:
```bash
cd evaluation/promptfoo
python - <<'PY'
import csv, json
from pathlib import Path
rows = json.loads(Path("datasets/rag_golden.json").read_text(encoding="utf-8"))
with open("golden_scenarios.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["query", "intent"])
    for r in rows: w.writerow([r["question"], r.get("intent", "")])
print("wrote", len(rows), "rows")
PY
```

## Run / operate
- Start the UI + nightly scheduler:
  `docker compose -f docker-compose.local.yml up -d promptfoo-server promptfoo-scheduler`
- The scheduler runs nightly at 02:00 (`evaluation/promptfoo/scheduler/crontab`).
- The scheduler container reaches the host's backend (`/chat`) and Ollama via
  `host.docker.internal`, and uses `PROMPTFOO_PYTHON=python3` (set in compose).
- Manual run from the host (e.g. before a release):
  ```bash
  cd evaluation/promptfoo
  PROMPTFOO_PYTHON=../../backend/.venv/bin/python \
  UMB_CHAT_BASE_URL=http://localhost:8000 \
  OLLAMA_BASE_URL=http://localhost:11434 \
  PROMPTFOO_REMOTE_API_BASE_URL=http://localhost:3001 \
  PROMPTFOO_REMOTE_APP_BASE_URL=http://localhost:3001 \
  npx --yes promptfoo@0.121.17 eval -c promptfooconfig.monitoring.yaml --share
  ```
- Requires the backend (`/chat`) + Ollama + restored KB to be up.

## How it works
A custom provider (`rag_chat_provider.py`) calls the real `/chat` (with
`include_retrieved_context`) and returns the answer + retrieved context + sources.
Assertions: `context-faithfulness` (answer grounded in retrieved context),
`llm-rubric` (answer relevant to the question), and a `javascript` official-source check.

## Caveat
The judge is the local `qwen2.5:7b-instruct` — scores are a **signal for human review**,
not absolute truth. It is report-only and does not gate releases. The deterministic CI gate
(`promptfoo_runner`) and the in-app `/eval` dashboard are unchanged.
