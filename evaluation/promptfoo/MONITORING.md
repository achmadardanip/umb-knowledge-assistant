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

## Coverage sets
The nightly config tests three CSV sources: `scenarios.csv` (curated), `golden_scenarios.csv`
(broad generated), and `adversarial_scenarios.csv` (robustness: typo / incomplete /
mixed-language / ambiguous, tagged with a `perturbation_type` var you can filter in the
viewer). Regenerate the adversarial set: `python -m app.evaluation.adversarial_scenarios --base 20`.

## Multi-model audits (occasional manual batch — heavy)
Two extra configs, graded by several local Ollama models (qwen2.5:7b, gemma2:9b, mistral:7b,
qwen2.5:14b, llama3.2:3b). Run them on demand, not nightly. Add `--filter-first-n 10` for a quick pass.
- **Judge reliability** — `promptfooconfig.judges.yaml`: grades the same answers with every
  judge as per-judge metrics (`faithfulness_<model>`, `relevance_<model>`) → see judge agreement.
- **Brain comparison** — `promptfooconfig.brains.yaml`: runs `/chat` under each answer model as
  columns (opt-in `answer_model` override) → which LLM brain is most faithful. Most UMB answers
  are deterministic (structured/FAQ) and identical across brains; the brain only matters for
  LLM-synthesized answers.

## Red-team (offline, curated attack suite)
`bash redteam.sh` runs a curated attack set (`redteam_scenarios.csv`: prompt-injection,
system-prompt extraction, PII elicitation, jailbreak-of-grounding, hallucination bait)
through the real `/chat`, and a local `qwen2.5:14b` judge scores whether each attack was
**resisted** (`attack_resisted` metric: pass = refused / stayed grounded / no leak / no
fabrication / didn't obey the injection). 100% local — no account needed. Add attacks by
appending rows to `redteam_scenarios.csv`. Report-only; heavy (qwen14b) → occasional batch.
> Note: Promptfoo's built-in `redteam` feature requires email/cloud verification, so this
> uses a curated local suite instead to stay fully offline.

## Export & share to engineers
- **Live link (best):** every `--share` run prints `http://<host>:3001/eval/?evalId=...` — send it.
- **Export a stored eval to JSON:** `bash export_report.sh [monitoring|judges|brains|<evalId>]`
  (writes `reports/export-<evalId>.json` and prints the share URL).
- **Self-contained HTML to email:** add `--output reports/report.html` to the eval command.

## Caveat
The judge is a local model (default `qwen2.5:7b-instruct`) — scores are a **signal for human
review**, not absolute truth. It is report-only and does not gate releases. The deterministic
CI gate (`promptfoo_runner`) and the in-app `/eval` dashboard are unchanged.
