#!/usr/bin/env bash
# Offline red-team of the UMB chatbot: runs the curated attack suite (redteam_scenarios.csv)
# through the real /chat and judges attack-resistance locally with qwen2.5:14b. No cloud/account.
# Usage:  bash redteam.sh [--filter-first-n N]
# Report-only. Heavy (qwen14b judge) -> occasional manual batch.
set -uo pipefail
cd "$(dirname "$0")"

export PROMPTFOO_PYTHON="${PROMPTFOO_PYTHON:-$(cd ../../backend/.venv/bin && pwd)/python}"
export UMB_CHAT_BASE_URL="${UMB_CHAT_BASE_URL:-http://localhost:8000}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
export PROMPTFOO_REMOTE_API_BASE_URL="${PROMPTFOO_REMOTE_API_BASE_URL:-http://localhost:3001}"
export PROMPTFOO_REMOTE_APP_BASE_URL="${PROMPTFOO_REMOTE_APP_BASE_URL:-http://localhost:3001}"

echo "[redteam] running curated offline attack suite (judge=qwen2.5:14b)"
npx --yes promptfoo@0.121.17 eval \
  -c promptfooconfig.redteam.yaml \
  --output reports/redteam_report.html \
  --share --no-progress-bar "$@"
echo "[redteam] HTML report: $(pwd)/reports/redteam_report.html"
