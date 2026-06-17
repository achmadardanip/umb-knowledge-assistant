#!/usr/bin/env bash
# Full Local Migration — restore a PostgreSQL backup (pg_restore) into the local container.
#
# Usage:  bash scripts/restore_local_db.sh <dump_file> [container]
# Example: bash scripts/restore_local_db.sh backups/umb_20260616T120000.dump
set -euo pipefail

DUMP="${1:?usage: restore_local_db.sh <dump_file> [container]}"
CONTAINER="${2:-umb-postgres}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-umb}"
BASENAME="$(basename "$DUMP")"

[ -f "$DUMP" ] || { echo "[restore] dump not found: $DUMP" >&2; exit 1; }
echo "[restore] copying $DUMP -> $CONTAINER:/tmp/$BASENAME"
MSYS_NO_PATHCONV=1 docker cp "$DUMP" "${CONTAINER}:/tmp/${BASENAME}"
echo "[restore] pg_restore into $DB_NAME (existing objects kept; --no-owner)"
docker exec "$CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" --no-owner --clean --if-exists "/tmp/${BASENAME}" || true
docker exec "$CONTAINER" rm -f "/tmp/${BASENAME}"
echo "[restore] done. Verify: docker exec $CONTAINER psql -U $DB_USER -d $DB_NAME -c 'select count(*) from chunks;'"
