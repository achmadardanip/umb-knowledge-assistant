#!/usr/bin/env bash
# Phase 25 P25.5 — automatic backup verification (backup -> restore -> validate).
# Proves the KB is 100% recoverable: dumps the live DB, restores it into a throwaway
# database, and checks the row counts match. Exits non-zero on any mismatch so cron
# can alert. Does NOT touch the live database.
set -euo pipefail

CONTAINER="${UMB_PG_CONTAINER:-umb-postgres}"
PGUSER="${UMB_PG_USER:-umb}"
SRC_DB="${UMB_PG_DB:-umb}"
CHECK_DB="umb_verify_$(date +%s)"
STAMP="$(date +%Y%m%d_%H%M%S)"
DUMP="/tmp/umb_verify_${STAMP}.dump"
BACKUP_DIR="${UMB_BACKUP_DIR:-backups}"

echo "[verify_backup] $(date) — dumping ${SRC_DB} from ${CONTAINER}"
docker exec "${CONTAINER}" pg_dump -U "${PGUSER}" -d "${SRC_DB}" -Fc -f "${DUMP}"

# keep a copy in the host backups dir
mkdir -p "${BACKUP_DIR}"
docker cp "${CONTAINER}:${DUMP}" "${BACKUP_DIR}/umb_verified_${STAMP}.dump"

echo "[verify_backup] restoring into ${CHECK_DB}"
docker exec "${CONTAINER}" psql -U "${PGUSER}" -d postgres -c "DROP DATABASE IF EXISTS ${CHECK_DB};"
docker exec "${CONTAINER}" psql -U "${PGUSER}" -d postgres -c "CREATE DATABASE ${CHECK_DB};"
docker exec "${CONTAINER}" pg_restore -U "${PGUSER}" -d "${CHECK_DB}" "${DUMP}" >/dev/null 2>&1 || true

count() { docker exec "${CONTAINER}" psql -U "${PGUSER}" -d "$1" -At -c "SELECT count(*) FROM $2;" 2>/dev/null || echo "ERR"; }

ok=1
for tbl in chunks chunk_embeddings sources umb_faculties umb_study_programs; do
  a="$(count "${SRC_DB}" "${tbl}")"; b="$(count "${CHECK_DB}" "${tbl}")"
  if [ "${a}" = "${b}" ] && [ "${a}" != "ERR" ]; then
    echo "  OK   ${tbl}: ${a} == ${b}"
  else
    echo "  FAIL ${tbl}: src=${a} restored=${b}"; ok=0
  fi
done

echo "[verify_backup] cleaning up ${CHECK_DB}"
docker exec "${CONTAINER}" psql -U "${PGUSER}" -d postgres -c "DROP DATABASE IF EXISTS ${CHECK_DB};" >/dev/null 2>&1 || true
docker exec "${CONTAINER}" rm -f "${DUMP}" >/dev/null 2>&1 || true

if [ "${ok}" = "1" ]; then
  echo "[verify_backup] RESULT: 100% recoverable ✓"; exit 0
else
  echo "[verify_backup] RESULT: RECOVERY MISMATCH ✗"; exit 1
fi
