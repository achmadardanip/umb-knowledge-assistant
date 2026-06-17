# Local PostgreSQL Persistence — Validation

**Date:** 2026-06-16 · Generated report (gitignored; not committed).

## Problem
The combined KB (11,414 chunks) was first loaded into a **manually-run** container with no
volume — data lived only in the container's writable layer (lost on `docker rm`). Docker
Desktop crashed once under host memory pressure, exposing the risk.

## Fix — named volume
`docker-compose.local.yml` already mounts a named volume for Postgres:
```yaml
services:
  postgres:
    volumes:
      - umb_local_pgdata:/var/lib/postgresql/data
volumes:
  umb_local_pgdata:
```
The running container was re-created the same way (named volume `umb_local_pgdata`), and the
combined KB was restored into it from a backup.

## Validation results
| Check | Result |
|---|---|
| Backup (`pg_dump -Fc`) → `backups/umb_combined.dump` | ✅ 40 MB |
| Restore (`pg_restore`) into volume-backed container | ✅ 11,414 chunks / 11,414 embeddings |
| **Container restart** (`docker restart umb-postgres`) | ✅ 11,414 chunks survive |
| Volume mount (`docker inspect`) | ✅ `volume umb_local_pgdata -> /var/lib/postgresql/data` |
| Docker restart / host reboot | ✅ guaranteed by the named-volume `local` driver (data lives in Docker's volume store, independent of the container lifecycle) |

Container-restart persistence was verified empirically; Docker-restart and host-reboot
persistence follow from the named volume (a `local`-driver named volume survives `docker rm`,
`docker compose down`, daemon restart, and host reboot — only `docker volume rm` deletes it).

## Backup procedure
```bash
docker exec umb-postgres pg_dump -U umb -d umb -Fc -f /tmp/umb.dump
docker cp umb-postgres:/tmp/umb.dump ./backups/umb_$(date +%F).dump
```

## Restore procedure
```bash
# into a fresh volume-backed container
docker run -d --name umb-postgres -e POSTGRES_USER=umb -e POSTGRES_PASSWORD=umb \
  -e POSTGRES_DB=umb -p 5433:5432 -v umb_local_pgdata:/var/lib/postgresql/data pgvector/pgvector:pg16
docker cp ./backups/umb_<date>.dump umb-postgres:/tmp/umb.dump
docker exec umb-postgres pg_restore -U umb -d umb --no-owner /tmp/umb.dump
```

## Note
`backups/` is gitignored (dumps are not source). For production-grade durability prefer
`docker compose -f docker-compose.local.yml up -d` (named volume managed by compose) over a
manual `docker run`.
