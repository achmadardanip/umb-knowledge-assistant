#!/usr/bin/env bash
# Run the nightly RAG monitoring eval and push results to the self-hosted server.
set -uo pipefail
cd /work/evaluation/promptfoo
echo "[$(date -u +%FT%TZ)] starting promptfoo monitoring eval"
npx --yes promptfoo@0.121.17 eval \
  -c promptfooconfig.monitoring.yaml \
  --share --no-progress-bar
echo "[$(date -u +%FT%TZ)] eval finished (exit $?)"
