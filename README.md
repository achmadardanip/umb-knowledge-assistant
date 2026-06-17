# UMB Knowledge Assistant

A grounded, multimodal **RAG** assistant for public Universitas Mercu Buana
information (`mercubuana.ac.id` + subdomains). Answers are synthesized **only**
from official sources that were crawled, indexed, and returned as cited context —
never from model prior knowledge. If nothing official is found, it abstains.

**Stack:** FastAPI · **PostgreSQL + pgvector** (single source of truth) · local E5 embeddings · Ollama
(`qwen2.5:7b-instruct`) · Tavily (live fallback) · Next.js. No hosted-DB dependency — runs fully local.

```
                     ┌─────────────────────────── FastAPI backend ───────────────────────────┐
  Next.js  ──/chat──▶│ intent → FAQ → entity → typed-graph → hybrid vector → reranker         │
  :3000             │            │                                  │            │            │
                     │            ▼ (low confidence)                 ▼            ▼            │
                     │         Tavily (UMB-only) ─▶ async KB acquire │   CGCV + citation guard │
                     └───────────────┬───────────────────────────────┬─────────────┬─────────┘
                       PostgreSQL + pgvector + GraphRAG         Ollama LLM      canonical URLs
```

**Deployment architecture (fully local):**
```
Next.js frontend (:3000)  ──▶  FastAPI backend (:8000)  ──▶  PostgreSQL + pgvector (:5432)
                                        └──▶ Ollama (qwen2.5:7b) / optional cloud LLM
```

---

## 1. Quick Start (5 minutes)

```bash
git clone <repo-url> umb-knowledge-assistant && cd umb-knowledge-assistant

# Backend
cd backend && python3.12 -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt && pip install -r requirements-local.txt && cd ..

# LLM + config
ollama pull qwen2.5:7b-instruct
cp .env.example .env        # local-first defaults (LOCAL_POSTGRES_MODE=true) + set TAVILY_API_KEY

# Local database (PostgreSQL + pgvector)
docker compose -f docker-compose.local.yml up -d postgres
cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m app.db.bootstrap_local   # schema + extensions

# Run (two terminals)
cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev

# Verify
curl http://localhost:8000/health     # {"status":"ok"}   →  open http://localhost:3000
```

## 2. Local Setup
- **Python 3.12+**, **Node 20+**, **Ollama**, ~3–4 GB disk (E5 + torch). GPU (CUDA/MPS) auto-used, CPU works.
- `requirements-local.txt` installs the local E5 embedder (+ optional reranker). Without it the app falls back to keyword-only retrieval.
- `.env` lives at the **project root** (not `backend/`).

## 3. Database — PostgreSQL + pgvector (default, no hosted dependency)
PostgreSQL + pgvector is the **single source of truth**. The app boots with no `SUPABASE_*`
variable (it is not a Supabase-SDK app — "Supabase" was only ever hosted Postgres).

```bash
# 1) install Docker Desktop, then bring up the local stack
docker compose -f docker-compose.local.yml up -d        # postgres + pgadmin (+ backend/frontend)
# 2) .env (already the default): LOCAL_POSTGRES_MODE=true
#    DATABASE_URL=postgresql://postgres:postgres@localhost:5432/umb   VECTOR_DB=pgvector
# 3) schema + extensions
cd backend && PYTHONPATH=. python -m app.db.bootstrap_local
# 4) load data — seed entities/FAQs, then crawl/ingest official sources
PYTHONPATH=. python -m app.ingestion.entity_extractor --seed
# 5) backend   6) frontend  (see Quick Start)
```
- pgAdmin: `http://localhost:5050` (`admin@local.dev` / `admin`).
- **Backup / restore:** `scripts/backup_local_db.sh` (daily, 30-day retention) · `scripts/restore_local_db.sh <dump>`.
- Full guide + persistence (named volume): **[docs/local_postgres.md](docs/local_postgres.md)**.

## 4. Optional — migrate from a hosted Postgres
Only if you have existing data in a hosted Postgres (e.g. Supabase): set
`SUPABASE_POOLER_DATABASE_URL` and run `python -m app.db.supabase_to_local` once to copy it
into local PostgreSQL. Not used at runtime; the application never requires it.

## 5. Ollama Setup
```bash
ollama pull qwen2.5:7b-instruct      # default answer model (CPU ok; ~30–100s/answer on CPU)
ollama list                          # confirm
```
Snappier demos: a smaller model (`qwen2.5:3b`), lower `LOCAL_LLM_MAX_TOKENS`, or a GPU.

## 6. Tavily Setup
Free key at https://tavily.com → `.env`: `TAVILY_API_KEY=...`. Used only as a
**confidence-gated, UMB-domain-only** live fallback; discoveries are acquired
into the KB so repeat questions are answered locally (no repeat Tavily calls).

## 7. Running the Frontend
```bash
cd frontend && npm install && npm run dev      # http://localhost:3000  (NEXT_PUBLIC_API_URL → :8000)
```

## 8. Running the Backend
```bash
cd backend && PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 9. Running the Full Stack
```bash
docker compose up -d        # postgres + redis + backend + frontend
```

## 10. Crawling UMB
```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.tavily_ingest      # Tavily map→extract→chunk→embed→index
# or the discovery + crawl pipeline (authorized, public pages only)
```
Then seed structured layers: `-m app.ingestion.entity_extractor --seed --mine`,
`-m app.ingestion.faq_seed`, `-m app.rag.canonical_urls`.

## 11. Building GraphRAG
```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.graph.build_graph          # co-occurrence graph
PYTHONPATH=. .venv/Scripts/python.exe -m app.graph.build_typed_graph    # typed entity graph
```

## 12. Running Evaluation
```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m pytest -q                                  # tests
PYTHONPATH=. .venv/Scripts/python.exe -m app.evaluation.benchmark --strategy agent  # 501-Q benchmark (all layers)
```
Reports → `data/reports/`. Metrics: answerability, official-source@1, citation
failures, intent-routing & follow-up accuracy, layer hit rates, latency.

## 13. Troubleshooting
| Symptom | Fix |
|---|---|
| Keyword-only retrieval / no dense | install `requirements-local.txt` (E5 needs torch) |
| `gin_trgm_ops does not exist` | `CREATE EXTENSION pg_trgm;` in its **own** committed tx, then the index |
| Hybrid retrieval ~10 s | apply `004_pg_trgm.sql` (trigram index) |
| Stale answer after a change | clear `rag_answer_cache`; restart uvicorn (no auto-reload) |
| Pytest crashes mid-run | stop the backend first (E5 in two processes exhausts memory) |
| High egress (only if using a hosted Postgres) | enable caching (default) + run the metadata prune — `EGRESS_REDUCTION_REPORT.md` |
| `.env` ignored | it must be at the **project root** |

---

## Retrieval flow
```
query ─▶ detect_intent ─▶ FAQ (canonical, 12–14) ─▶ Entity (7–10) ─▶ Typed Graph (9)
        ─▶ Hybrid Vector (keyword+dense) ─▶ intent-host filter (+boost / −penalty)
        ─▶ confidence check ─▶ (low?) Tavily UMB-only ─▶ rerank ─▶ CGCV + citation/URL guard ─▶ answer
```
Structured layers are pinned above vector unless intent-demoted; the reranker only reorders vector passages.

## Intent routing
```
detect_intent(q) ∈ {admissions, tuition, scholarship, sia, sso, library, faculty,
                    study_program, lecturer, campus, academic_calendar/regulations,
                    student_services, general}
  → entity-intent compatibility (demote off-intent structured contexts)
  → INTENT_HOSTS allowlist (boost on-intent host, penalise off-intent vector chunk)
```

## KB acquisition flow (Tavily fallback)
```
KB miss / low confidence ─▶ Tavily search (site:mercubuana.ac.id) ─▶ UMB filter
  ─▶ fetch/extract ─▶ answer user FIRST
  ─▶ [background thread] clean → chunk → embed → save KB → record discovery cache
  ─▶ future identical question → served from KB (no Tavily)
```

## Reports & docs
`docs/knowledge_layers.md` (entity/FAQ/graph) · `docs/local_postgres.md` ·
`EGRESS_REDUCTION_REPORT.md` · `V2_REBUILD_REPORT.md` · `PHASE5_VALIDATION_REPORT.md`.
