# Local PostgreSQL Deployment (no Supabase)

Run the entire UMB Knowledge Assistant locally — FastAPI + **local Postgres
(pgvector)** + Next.js + Ollama — with zero Supabase dependency. (v3 P6)

```
┌──────────┐   ┌──────────┐   ┌─────────────────────┐   ┌────────┐
│ Next.js  │──▶│ FastAPI  │──▶│ Postgres + pgvector  │   │ Ollama │
│ :3000    │   │ :8000    │   │ :5432 (docker)       │   │ :11434 │
└──────────┘   └────┬─────┘   └─────────────────────┘   └────────┘
                    └──────────▶ Redis :6379 (cache, optional)
```

## 1. Start the data services

```bash
docker compose up -d postgres redis
docker compose ps          # wait for "healthy"
```

`docker-compose.yml` provides `pgvector/pgvector:pg16` (user/pass/db = `umb`) and
`redis:7`.

## 2. Point the app at local Postgres

In `.env` (project root):

```bash
LOCAL_POSTGRES_MODE=true
LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5432/umb
REDIS_URL=redis://localhost:6379/0      # optional; enables the shared cache
```

`LOCAL_POSTGRES_MODE=true` overrides Supabase for `database_url` (see
`app/core/config._resolve_database_url`).

## 3. Bootstrap the schema

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.db.bootstrap_local
```

Creates the `vector` + `pg_trgm` extensions, all ORM tables, and the trigram +
HNSW indexes. Idempotent.

## 4. (Optional) Migrate existing data from Supabase

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.db.supabase_to_local \
    --source "$SUPABASE_POOLER_DATABASE_URL" \
    --target "postgresql://umb:umb@localhost:5432/umb"
```

Copies (idempotent, FK-ordered): `sources, documents, source_assets,
extracted_segments, chunks, chunk_embeddings, umb_* entities, umb_faqs,
canonical_urls, knowledge_discovery_cache`. The GraphRAG artifacts
(`data/graph/*.json`) are plain files — they ship with the repo.

Fresh install instead of migrating? Run the crawl + index pipeline, then
`python -m app.graph.build_graph`, `python -m app.graph.build_typed_graph`,
`python -m app.ingestion.entity_extractor --seed`, `python -m app.ingestion.faq_seed`,
and `python -m app.rag.canonical_urls`.

## 5. Run the app

```bash
# backend
cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
# frontend
cd frontend && npm run dev
```

Or the whole stack in containers: `docker compose up -d` (the `backend` service
sets `LOCAL_POSTGRES_MODE=true` and talks to `postgres`/`redis` by service name).

## Verify

```bash
curl http://localhost:8000/health          # {"status":"ok"}
```

## Notes
- pgvector image already bundles the `vector` extension; `pg_trgm` is created by the bootstrap.
- Set `REDIS_URL` to share the FAQ/entity/retrieval cache across backend workers; without it an in-process cache is used.
- To go back to Supabase: set `LOCAL_POSTGRES_MODE=false` (or unset) in `.env`.
