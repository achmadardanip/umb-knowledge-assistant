# Setup Guide — run the UMB Knowledge Assistant in ~15 minutes

Prerequisites: **Python 3.12**, **Node 20+**, **Docker 24+** (Compose v2), and (for chat
answers) **Ollama**. No Supabase — PostgreSQL + pgvector is the only database.

## 1. Clone & Python env (3 min)
```bash
git clone https://github.com/achmadardanip/umb-knowledge-assistant.git
cd umb-knowledge-assistant/backend
python -m venv .venv && .venv\Scripts\activate        # Windows  (or: source .venv/bin/activate)
pip install -r requirements.txt
cd ..
```

## 2. Environment (1 min)
```bash
cp .env.example .env
```
Key variables (see "Environment variables" below). The defaults run fully local.

## 3. Database — PostgreSQL + pgvector (2 min)
The repo already runs a container named **`umb-postgres` on host port 5433** (creds `umb/umb`,
db `umb`, named volume `umb_local_pgdata`). If it's not running:
```bash
docker start umb-postgres                  # if it already exists
# OR create it fresh:
docker run -d --name umb-postgres -e POSTGRES_USER=umb -e POSTGRES_PASSWORD=umb \
  -e POSTGRES_DB=umb -p 5433:5432 -v umb_local_pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```
> Don't `docker compose up postgres` if `umb-postgres` already exists — it conflicts on the
> name. Use the existing container (your data lives on the `umb_local_pgdata` volume).

## 4. Schema + KB (3 min)
```bash
cd backend
set LOCAL_POSTGRES_MODE=true & set LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb
python -m app.db.bootstrap_local           # extensions + tables + HNSW/trgm indexes
python -m app.db.migrate_freshness         # freshness columns + crawl_registry
python -m app.db.migrate_session_memory    # memory_key/value columns
# restore the KB dump (if starting from a backup):
#   pg_restore -d umb backups/umb_*.dump    (or run the ingestion pipeline)
```
Verify: `python scripts/validate_local.py --base http://localhost:8000` (after step 6).

## 5. Ollama (2 min) — for chat answers
```bash
ollama serve            # if not already running (:11434)
ollama pull qwen2.5:3b-instruct   # 3b = much faster on CPU than 7b
```

## 6. Backend (1 min) — MUST point at :5433
```bash
cd backend
# Windows PowerShell:
$env:LOCAL_POSTGRES_MODE="true"; $env:LOCAL_POSTGRES_URL="postgresql://umb:umb@localhost:5433/umb"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Check: http://localhost:8000/health → `{"status":"ok"}`; `/stats` should show the real chunk count.

## 7. Frontend (2 min)
```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

## 8. Validate
- Open http://localhost:3000 — send "Siapa dekan FEB?".
- Dashboards: http://localhost:3000/dashboard and /analytics.
- Benchmarks: `cd backend && python -m app.evaluation.production_certification`.

## Environment variables (essentials)
| Var | Purpose | Default |
|---|---|---|
| `LOCAL_POSTGRES_MODE` | use local PostgreSQL | `true` |
| `LOCAL_POSTGRES_URL` | DB connection (**:5433**) | `postgresql://umb:umb@localhost:5433/umb` |
| `SESSION_MEMORY_BACKEND` | `memory` (1 worker) or `postgres` (multi-worker) | `memory` |
| `TAVILY_API_KEY` | enable web fallback (optional) | unset |
| `CGCV_ENTAILMENT_MODE` | `lexical` (CPU) or `nli` (GPU) | `lexical` |
| `NEXT_PUBLIC_API_URL` (frontend) | backend URL | `http://localhost:8000` |

See **TROUBLESHOOTING.md** if anything fails.
