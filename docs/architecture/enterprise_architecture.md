# Enterprise Architecture Diagram (Phase 26.5)

```
                                   ┌──────────────┐
                                   │     User     │
                                   └──────┬───────┘
                                          │ HTTPS
                                ┌─────────▼──────────┐
                                │  Next.js Frontend  │  chat · /dashboard · /analytics
                                │  (React 19, TS)    │  source drawer · freshness badges
                                └─────────┬──────────┘
                                          │ HTTP / SSE
                                ┌─────────▼──────────┐
                                │   FastAPI Backend  │  rate-limit · CORS · 40 routes
                                │   (Python 3.12)    │
                                └─────────┬──────────┘
                                          │
                 ┌────────────────────────┼─────────────────────────┐
                 │                        │                         │
        ┌────────▼────────┐      ┌────────▼────────┐       ┌────────▼─────────┐
        │ Retrieval Agent │      │ Session Memory  │       │  Observability   │
        │ intent→FAQ→     │◄────►│ MemoryProvider  │       │ /system/* /alerts│
        │ Entity→Graph→   │      │  ├ InMemory     │       │ /analytics       │
        │ Vector→Rerank   │      │  └ Postgres ────┼──┐    │ dashboards       │
        └───┬─────────┬───┘      └─────────────────┘  │    └────────┬─────────┘
            │         │                                │             │
   ┌────────▼──┐  ┌───▼──────────┐                     │             │
   │ GraphRAG  │  │ Entity Layer │                     │             │
   │ (typed,   │  │ faculty/prog/│                     │             │
   │ in-memory)│  │ dean/kaprodi │                     │             │
   └────┬──────┘  └───┬──────────┘                     │             │
        │             │                                │             │
        ▼             ▼                                ▼             ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │                    PostgreSQL  +  pgvector  (sole source of truth)     │
  │  chunks · chunk_embeddings(HNSW) · sources · umb_*(entities) ·         │
  │  crawl_registry · chat_sessions · chat_messages · chat_memories ·      │
  │  feedback · documents · discovered_*                                   │
  └───────────────────────────▲──────────────────────────────────────────┘
                               │
                     ┌─────────┴──────────┐
                     │ Incremental Crawler│  scheduler (cron/systemd/docker)
                     │ due→fetch→detect→  │  → re-ingest only changed pages
                     │ reingest/skip      │  → /system/crawl, /crawl/status
                     └────────────────────┘

  Ops loop:  Alerting (app.ops.alerts) ─ retrieval/crawl/db/embeddings/freshness
             Backup verification (scripts/verify_backup.sh, nightly) ─ 100% recoverable
             Promptfoo CI (913 tests) + benchmark gate on PR/push
```

## Components
| Component | Tech | Module(s) |
|---|---|---|
| Frontend | Next.js 16 / React 19 | `frontend/app/**` |
| FastAPI | Python 3.12 | `app/main.py`, `app/api/*` |
| GraphRAG | in-memory typed graph | `app/graph/*` |
| Entity Layer | deterministic lookups | `app/retrieval/entity_retriever.py` |
| Session Memory | InMemory / Postgres provider | `app/chat/memory_provider.py`, `session_memory.py` |
| PostgreSQL + pgvector | PG16/17 + HNSW | `app/db/*` |
| Crawler | incremental, scheduled | `app/crawl/*`, `ops/*` |
| Monitoring | live endpoints + dashboard | `app/api/routes_system.py`, `routes_analytics.py` |
| Analytics | feedback + failures | `app/api/routes_analytics.py`, `/analytics` |
