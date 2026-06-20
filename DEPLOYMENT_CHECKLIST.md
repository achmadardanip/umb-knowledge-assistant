# UMB Knowledge Assistant — Production Deployment Checklist (Phase 23)

A pre-flight checklist for deploying the local PostgreSQL + pgvector stack.
Status as of Phase 23: **PRODUCTION_CERTIFIED_V1**.

## 1. Database
- [ ] `docker compose -f docker-compose.local.yml up -d postgres` (pgvector/pgvector:pg16/17)
- [ ] Restore the KB dump: `pg_restore -d umb backups/umb_pre_prune_*.dump` (or bootstrap + ingest)
- [ ] `python -m app.db.bootstrap_local` (extensions + ORM tables + HNSW/trgm indexes)
- [ ] `python -m app.db.migrate_freshness` (freshness columns + crawl_registry)
- [ ] Verify counts: `GET /system/stats` → chunks ≈ 5,911, sources, 7 faculties, 20 programs
- [ ] Named volume `umb_local_pgdata` mounted (data persistence across restarts)
- [ ] Backup cron: `scripts/backup_local_db.sh` daily; tested restore via `scripts/restore_local_db.sh`

## 2. Backend (FastAPI)
- [ ] `LOCAL_POSTGRES_MODE=true`, `LOCAL_POSTGRES_URL` set; **no Supabase env**
- [ ] `uvicorn app.main:app --host 0.0.0.0 --port 8000` (use a free port; 8000/8001 may be held)
- [ ] **Run multiple workers** (`--workers N`) only with the chat_memories-backed session
      memory (the in-process store is per-worker) — OR pin sticky sessions at the LB
- [ ] Health: `GET /system/health` = ok; `GET /health` = ok
- [ ] Reranker / embedder models present (E5 multilingual-small); GPU optional

## 3. Frontend (Next.js)
- [ ] `NEXT_PUBLIC_API_URL` → backend URL
- [ ] `npm run build` ✓ (routes: `/`, `/dashboard`, `/analytics`)
- [ ] `npm run start` behind the LB

## 4. Observability
- [ ] `/dashboard` (KB / Retrieval / Crawl / Freshness / Graph / Database)
- [ ] `/analytics` (feedback rates, top failures)
- [ ] `/system/*` + `/crawl/status` reachable for monitoring/alerting

## 5. Incremental crawl
- [ ] `python -m app.crawl.crawler_scheduler --reclassify` (tag archive=monthly)
- [ ] Schedule `crawler_scheduler --tick` via **cron/systemd-timer** (daily critical / weekly / monthly)
- [ ] Verify `crawl_efficiency` skip-rate > 90%

## 6. Quality gates (CI — must pass before deploy)
- [ ] `python -m app.evaluation.promptfoo_runner` ≥ 0.97 overall
- [ ] `python -m app.evaluation.benchmark --strategy agent_hybrid` → official_top ≥ 0.99, citation_failure ≤ 0.01
- [ ] `python -m app.evaluation.followup_benchmark_v2` → retention ≥ 0.95, resolution ≥ 0.95
- [ ] `python -m app.evaluation.production_certification` → PRODUCTION_CERTIFIED_V1
- [ ] `python -m app.evaluation.load_test` → 0 errors, p95 < 1s, no memory leak
- [ ] GitHub Action `promptfoo-eval` green on the release commit

## 7. Security / data
- [ ] Official UMB sources only; provenance + citations intact
- [ ] No `.env` / secrets committed; reports + backups gitignored
- [ ] Browse-index prune backup retained for rollback

## Known operational risks
- In-process session memory is per-worker (single-worker safe; multi-worker needs the DB-backed variant).
- Docker Desktop instability on the dev host (recover: restart + `docker start umb-postgres`).
- Full NLI groundedness pending a ≥4 GB GPU host (lexical CPU gate active).
- Live crawler scheduler must be wired to an OS scheduler for true autonomy.
