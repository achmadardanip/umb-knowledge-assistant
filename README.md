# UMB Knowledge Assistant

A production-grade, **fully-local** Retrieval-Augmented Generation (RAG) assistant for
**Universitas Mercu Buana (UMB)**. It answers questions about faculties, study programs,
deans, kaprodi, accreditation, admissions (PMB), tuition, scholarships, campuses and
academic services **strictly from official UMB sources**, with citations on every answer.

> Status: **PRODUCTION_CERTIFIED_V1** — official_top 0.998 · citation_failure 0.0 ·
> follow_up 1.0 · entity_accuracy 1.0 · faculty_leakage 0 · context_retention 1.0.

---

## Project Overview

**What it is.** A grounded question-answering system over a curated corpus of official
`*.mercubuana.ac.id` pages and PDFs. It combines a typed **GraphRAG** + structured
**entity layer** + **pgvector** semantic search, behind a FastAPI API and a Next.js chat UI.

**Goals.**
- Answer only from official UMB sources, always with citations (no hallucination).
- Resolve named entities (faculty / program / dean / kaprodi / accreditation) deterministically.
- Maintain conversation context across follow-up turns (session memory).
- Stay fully local — **PostgreSQL + pgvector is the single source of truth** (no Supabase).
- Be observable, evaluable, and self-maintaining (monitoring, Promptfoo, incremental crawler).

**Core capabilities.**
- Hybrid retrieval: FAQ → Entity → typed GraphRAG → vector (pgvector) → reranker.
- Deterministic entity resolution with program/faculty disambiguation (0 faculty leakage).
- Session entity memory + elliptical follow-up resolution (“beliau…”, “akreditasinya…”).
- Content freshness tracking + stale-source penalty; incremental change-detecting crawler.
- Streaming chat (SSE) with stop-generation; source drawer with citations + freshness badges.
- Monitoring dashboard, feedback analytics, Promptfoo continuous evaluation, load tests.

**Technology stack.**

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind, shadcn/ui, @tanstack/react-query |
| Backend | FastAPI (Python 3.12), SQLAlchemy, Uvicorn |
| Vector DB | PostgreSQL 16/17 + **pgvector** (HNSW) + pg_trgm |
| Embeddings | `intfloat/multilingual-e5-small` (local, CPU) |
| Graph | In-memory typed property graph built from the `umb_*` entity tables |
| LLM providers | Local Ollama / LM Studio, OpenAI, Gemini, Claude, Groq, OpenRouter, Hugging Face, **Azure AI Foundry** |
| Eval | Promptfoo + custom deterministic benchmark suite |
| Infra | Docker Compose (local), named volume `umb_local_pgdata` |

> **Azure AI Foundry** (Phase 30): set `AZURE_FOUNDRY_ENDPOINT`, `AZURE_FOUNDRY_API_KEY`,
> `AZURE_FOUNDRY_DEPLOYMENT`, `AZURE_FOUNDRY_API_VERSION` and pick "☁ Azure AI Foundry" in the
> provider selector (or `ANSWER_PROVIDER=azure_foundry`). Status shows in `/system/health` + `/dashboard`.

---

## Architecture

```
            User
             │
             ▼
   ┌───────────────────┐
   │  Next.js Frontend │  chat UI · /dashboard · /analytics · source drawer
   └─────────┬─────────┘
             │ HTTP / SSE
             ▼
   ┌───────────────────┐
   │  FastAPI Backend  │  /chat /chat/stream /sessions /system/* /analytics ...
   └─────────┬─────────┘
             │
             ▼
   ┌───────────────────┐   intent → FAQ → Entity → GraphRAG → Vector → Reranker
   │  Retrieval Agent  │
   └───┬─────────┬─────┘
       │         │
       ▼         ▼
 ┌──────────┐ ┌───────────────┐
 │ GraphRAG │ │ Entity Layer  │  faculty/program/dean/kaprodi/accreditation
 │  (typed) │ └──────┬────────┘
 └────┬─────┘        │
      │     ┌────────▼────────┐
      │     │ Session Memory  │  per-session entities; elliptical follow-up resolution
      │     └────────┬────────┘
      ▼              ▼
   ┌────────────────────────────┐
   │  PostgreSQL + pgvector      │  chunks · chunk_embeddings · sources · umb_* · sessions
   └────────────────────────────┘
```

### Pipelines

- **Retrieval pipeline** — `intent_gate` classifies the query; the agent pins non-demoted
  structured contexts (FAQ + entity + typed-graph relations) above the pgvector results,
  fuses keyword+dense (`HybridRetriever`), applies a host-authority/topic prior, and filters
  non-content browse pages. See [docs/architecture/retrieval.md](docs/architecture/retrieval.md).
- **Entity resolution pipeline** — `entity_retriever.query_entities` does deterministic
  lookups over the `umb_*` tables with program>faculty priority and a query-aware tie-break
  (dekan→faculty, kaprodi→program). See [docs/architecture/entity_resolution.md](docs/architecture/entity_resolution.md).
- **Session memory pipeline** — `session_memory` remembers the established subject; on a
  follow-up `followup_resolution` injects it. See [docs/architecture/session_memory.md](docs/architecture/session_memory.md).
- **Citation pipeline** — every answer's claims are tied to retrieved official sources;
  unverified answers are refused (no source cards on a non-answer). See `app/rag/answer_generator.py`, `app/verification/`.
- **Freshness pipeline** — sources carry crawl/verify dates; the payload exposes
  freshness + a stale penalty. See [docs/architecture/freshness.md](docs/architecture/freshness.md).
- **Crawl pipeline** — `crawl_registry` + `detect_changed_content` re-ingest only changed
  pages. See [docs/architecture/crawler.md](docs/architecture/crawler.md).

---

## Database Schema

PostgreSQL (24 tables). Key tables:

| Table | Purpose |
|---|---|
| `sources` | Crawled official pages/PDFs + provenance + freshness (`fetched_at`, `content_hash`, `first_seen_date`, `last_verified_date`, …) |
| `documents` | Per-source extracted documents |
| `chunks` | Retrievable text chunks (`chunk_text`, `source_id`, `metadata`, `embedding`) |
| `chunk_embeddings` | Sidecar pgvector embeddings (HNSW index); 1 per chunk |
| `umb_faculties` | 7 faculties (name, dean, accreditation, campus, contacts) |
| `umb_study_programs` | 20 programs (head_of_program/kaprodi, accreditation, faculty) |
| `umb_campuses` / `umb_contacts` / `umb_services` / `umb_scholarships` / `umb_faqs` | Structured entity tables |
| `crawl_registry` | Incremental-crawl ledger (url, hash, content_type, cadence, status) |
| `chat_sessions` | Conversations (title, memory toggle) |
| `chat_messages` | Turns (`role`, `content`, `sources`, `not_found`, `confidence_score`) |
| `chat_memories` | Persisted per-session memory items |
| `feedback` | 👍/👎 ratings keyed by `message_id` |
| `discovered_hosts` / `discovered_urls` / `canonical_urls` | Crawl discovery + scope |

> GraphRAG uses an **in-memory typed graph** built from the `umb_*` tables at runtime
> (no separate graph tables) — 69 nodes / 73 edges (faculty/program/person/campus/…).

---

## Local Development Setup

**Requirements**
- Python **3.12**
- Node **20+** (tested on 25)
- Docker **24+** (Docker Compose v2)
- PostgreSQL **16/17** with **pgvector** (provided by the `pgvector/pgvector` image)

**Steps**

```bash
# 1. Clone
git clone https://github.com/achmadardanip/umb-knowledge-assistant.git
cd umb-knowledge-assistant

# 2. Python env
cd backend && python -m venv .venv && .venv/Scripts/activate    # (Windows) or source .venv/bin/activate
pip install -r requirements.txt && cd ..

# 3. Configure env (copy and edit)
cp .env.example .env        # set LOCAL_POSTGRES_MODE=true and LOCAL_POSTGRES_URL

# 4. Start PostgreSQL + pgvector
docker compose -f docker-compose.local.yml up -d postgres pgadmin

# 5. Bootstrap + restore KB
cd backend
LOCAL_POSTGRES_MODE=true python -m app.db.bootstrap_local       # extensions, tables, HNSW/trgm indexes
LOCAL_POSTGRES_MODE=true python -m app.db.migrate_freshness     # freshness columns + crawl_registry
#   then restore the KB dump:  pg_restore -d umb backups/umb_*.dump   (or run the ingestion pipeline)

# 6. Run backend  (use a free port; 8000/8001 may be occupied on some hosts)
LOCAL_POSTGRES_MODE=true LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb \
  uvicorn app.main:app --host 0.0.0.0 --port 8000

# 7. Run frontend
cd ../frontend && npm install && npm run dev      # http://localhost:3000

# 8. Validate endpoints
python scripts/validate_local.py --base http://localhost:8000

# 9. Run benchmarks
cd backend
python -m app.evaluation.benchmark --strategy agent_hybrid --top-k 5 --out ../reports/bench.json
python -m app.evaluation.production_certification
```

---

## Docker Deployment

`docker-compose.local.yml` defines four services, all with healthchecks + `restart: unless-stopped`:

| Service | Image | Port | Notes |
|---|---|---|---|
| `postgres` | pgvector/pgvector:pg17 | 5432 | volume `umb_local_pgdata` |
| `pgadmin` | dpage/pgadmin4 | 5050 | admin@local.dev / admin |
| `backend` | build ./backend | 8000 | depends_on postgres+redis healthy |
| `frontend` | build ./frontend | 3000 | waits for backend health |

```bash
docker compose -f docker-compose.local.yml up -d        # full stack
```

---

## Backup & Restore

```bash
scripts/backup_local_db.sh         # pg_dump -Fc -> backups/
scripts/restore_local_db.sh        # pg_restore from a chosen dump
```
A pre-prune backup (`backups/umb_pre_prune_*.dump`) is retained for rollback. Backups are gitignored.

---

## Monitoring

- **Dashboard** `/dashboard` — KB / Retrieval / Crawl / Freshness / Graph / Database panels (30s refresh).
- **Analytics** `/analytics` — feedback rates + top failure categories.
- **Stats endpoints** — `/stats`, `/system/{health,stats,crawl,freshness,graph,database}`, `/crawl/status`.

---

## Promptfoo Evaluation

```bash
cd backend
# Retrieval benchmark (production path)
python -m app.evaluation.benchmark --strategy agent_hybrid --top-k 5 --out ../reports/bench.json
# Entity + faculty + conversation benchmarks
python -m app.evaluation.entity_benchmark
python -m app.evaluation.faculty_disambiguation_benchmark
python -m app.evaluation.followup_benchmark_v2
# Promptfoo suite (913 tests) — deterministic gate
python -m app.evaluation.promptfoo_datasets        # (re)generate datasets
python -m app.evaluation.promptfoo_runner          # deterministic, no LLM
npx promptfoo eval -c evaluation/promptfoo/promptfooconfig.yaml   # LLM-judge view (CI)
```
CI: `.github/workflows/promptfoo.yml` runs the gate + benchmark + Promptfoo on every PR/push.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `could not send SSL negotiation packet: Socket is not connected` | Docker Desktop crashed — restart it, then `docker start umb-postgres`. Data persists on `umb_local_pgdata`. |
| `/health` returns 404 / Prometheus metrics on :8000/:8001 | Another container holds the port — run uvicorn on a free port (e.g. `--port 8010`). |
| `role "umb" does not exist` | Container mounted an empty/compose volume — recreate it on `umb_local_pgdata`. |
| Slow chat answers (30–105 s) | Hardware-bound: local CPU embedder + local LLM. Retrieval itself is ~p50 8 ms. |
| Empty retrieval for topical queries via `--strategy agent` | That strategy is a dense-only lower bound; production uses `--strategy agent_hybrid`. |

---

## Production Notes

**Known limitations**
- Session memory is **in-process per worker** — single-worker safe; multi-worker needs the
  `chat_memories`-backed variant or sticky LB sessions.
- Full NLI groundedness certification is **pending a ≥4 GB GPU** (lexical CPU gate active).
- The incremental crawler scheduler must be wired to **cron/systemd-timer** for autonomy.

**Operational guidance**
- Restore the KB from a dump before serving; verify `/system/stats`.
- Schedule daily backups; keep at least the latest pre-change dump.
- Watch `/dashboard` (stale sources, missing embeddings, dangling edges) and `/analytics` (top failures).
- Gate releases on the benchmark + certification + load test (see `DEPLOYMENT_CHECKLIST.md`).

See [docs/architecture/](docs/architecture/) for deep dives and [GAP_ANALYSIS.md](GAP_ANALYSIS.md) for the roadmap.
