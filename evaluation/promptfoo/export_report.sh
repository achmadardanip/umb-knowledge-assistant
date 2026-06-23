#!/usr/bin/env bash
# Export a Promptfoo eval to a shareable JSON file + print the self-hosted share URL,
# so results can be handed to engineers.
#
# Usage:
#   bash export_report.sh                 # latest 'monitoring' eval
#   bash export_report.sh judges          # latest judge-audit eval
#   bash export_report.sh brains          # latest brain-comparison eval
#   bash export_report.sh eval-AbC-2026..  # a specific evalId
#
# For a self-contained HTML report to email, add --output to the eval run itself, e.g.:
#   ... npx promptfoo@0.121.17 eval -c promptfooconfig.monitoring.yaml --output reports/report.html --share
set -uo pipefail
cd "$(dirname "$0")"

ARG="${1:-monitoring}"
SERVER="${PROMPTFOO_REMOTE_APP_BASE_URL:-http://localhost:3001}"
PF="npx --yes promptfoo@0.121.17"

case "$ARG" in
  monitoring|judges|brains)
    REPORT="reports/promptfoo_${ARG}_latest.json"
    [ -f "$REPORT" ] || { echo "no report yet: $REPORT (run that eval first)" >&2; exit 1; }
    EVAL_ID=$(python3 -c "import json;print(json.load(open('$REPORT'))['evalId'])") ;;
  *) EVAL_ID="$ARG" ;;
esac

OUT="reports/export-${EVAL_ID}.json"
echo "[export] evalId=$EVAL_ID"
$PF export eval "$EVAL_ID" -o "$OUT" >/dev/null 2>&1 \
  && echo "[export] JSON  : $(pwd)/$OUT" \
  || echo "[export] JSON export failed (is the evalId correct / server up?)" >&2
echo "[export] Share : ${SERVER}/eval/?evalId=${EVAL_ID}"
