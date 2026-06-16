#!/usr/bin/env bash
# Phase-10 STEP 7 — automated local PostgreSQL backup (pg_dump, dated, with retention).
#
# Usage:   bash scripts/backup_local_pg.sh [container] [retention_days]
# Cron:    0 3 * * *  cd /path/to/repo && bash scripts/backup_local_pg.sh >> backups/backup.log 2>&1
set -euo pipefail

CONTAINER="${1:-umb-postgres}"
RETENTION_DAYS="${2:-14}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/backups"
STAMP="$(date +%Y%m%dT%H%M%S)"
DUMP="umb_${STAMP}.dump"

mkdir -p "$OUT_DIR"
echo "[backup] $(date -u +%FT%TZ) dumping $CONTAINER -> $DUMP"
docker exec "$CONTAINER" pg_dump -U umb -d umb -Fc -f "/tmp/${DUMP}"
MSYS_NO_PATHCONV=1 docker cp "${CONTAINER}:/tmp/${DUMP}" "${OUT_DIR}/${DUMP}"
docker exec "$CONTAINER" rm -f "/tmp/${DUMP}"
echo "[backup] wrote ${OUT_DIR}/${DUMP} ($(du -h "${OUT_DIR}/${DUMP}" | cut -f1))"

# Retention: delete dumps older than RETENTION_DAYS.
find "$OUT_DIR" -name 'umb_*.dump' -type f -mtime "+${RETENTION_DAYS}" -print -delete || true
echo "[backup] done (retention ${RETENTION_DAYS}d)"
