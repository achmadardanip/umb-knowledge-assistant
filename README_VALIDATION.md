# README Validation (Phase 12)

- Architecture is local-first: Frontend (Next.js :3000) → Backend (FastAPI :8000) → PostgreSQL + pgvector (:5432). Diagram added.
- Supabase setup/migration/deployment removed from the primary flow; demoted to an OPTIONAL one-time data-migration note. The app boots with NO Supabase variable (verified).
- Added: local install, Docker startup (docker-compose.local.yml, pg17), backup & restore (scripts/backup_local_db.sh + restore_local_db.sh), troubleshooting, memory note.
- Verified: no `SUPABASE_*` runtime requirement; `LOCAL_POSTGRES_MODE=true` + `DATABASE_URL=local` + `VECTOR_DB=pgvector` are the defaults in `.env.example`.
