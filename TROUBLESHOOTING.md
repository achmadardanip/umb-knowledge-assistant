# Troubleshooting

Real issues seen on this stack and their fixes.

## "Session not found" in the chatbot
**Cause:** the browser cached a `session_id` from a previous/different database; it doesn't
exist in the current DB.
**Fix:** already handled — the backend now creates a fresh session for unknown ids and the
frontend adopts the returned `session_id` (one conversation = one history). If you still see
it, hard-refresh (Ctrl+Shift+R) to clear the stale cached id.

## `column sources.extraction_date does not exist`
**Cause:** the backend is pointed at a database that never got the `migrate_freshness`
migration (e.g. an old/stale DB on a different port).
**Fix:** point the backend at the certified DB and run the migrations:
```bash
$env:LOCAL_POSTGRES_URL="postgresql://umb:umb@localhost:5433/umb"
python -m app.db.bootstrap_local
python -m app.db.migrate_freshness
python -m app.db.migrate_session_memory
```

## "Failed to fetch" when chatting
**Cause:** the frontend (default `:8000`) is hitting a stale/down backend, or no backend is
running there.
**Fix:** run ONE backend on `:8000` against `:5433` (see SETUP_GUIDE step 6). Confirm
`curl http://localhost:8000/stats` shows the correct chunk count (not an old number).

## Docker: `Conflict. The container name "/umb-postgres" is already in use`
**Cause:** `docker compose up postgres` tries to create a container that already exists.
**Fix:** use the existing container — `docker start umb-postgres`. Only `docker rm -f
umb-postgres` if you intend to recreate it (data persists on the `umb_local_pgdata` volume).

## `could not send SSL negotiation packet: Socket is not connected`
**Cause:** Docker Desktop crashed (memory pressure on small hosts).
**Fix:** restart Docker Desktop, then `docker start umb-postgres`. Data is safe on the
named volume.

## `/health` returns 404 or Prometheus metrics on :8000/:8001
**Cause:** another container (e.g. an inference/exporter stack) holds the port.
**Fix:** stop it, or run the backend on a free port (`--port 8010`) and set
`NEXT_PUBLIC_API_URL` accordingly.

## Chat answers are very slow (1–3+ min)
**Cause:** the local LLM (Ollama) runs on CPU; `qwen2.5:7b` is heavy.
**Fix:** `ollama pull qwen2.5:3b-instruct` and select it; ensure `ollama serve` is up
(`curl http://localhost:11434/api/tags`). Retrieval itself is fast (~p50 8 ms).

## Dark mode text unreadable
**Cause/Fix:** resolved — legacy hardcoded colors were remapped to shadcn semantic tokens
(`bg-card`, `text-foreground`, `bg-accent`, …). Rebuild the frontend if you see stale styles.

## Hydration mismatch warning
**Cause/Fix:** resolved — `ThemeToggle` is guarded on `mounted` and dates use a deterministic
formatter. A browser extension that mutates the DOM can also trigger it; test in a clean profile.

## `benchmark.py` exits with Segmentation fault (139)
**Cause:** native torch crash under host memory pressure during the heavy generation pass.
**Fix:** it's environmental, not a code bug. Use the segfault-free retrieval proof:
`python -m app.evaluation.promptfoo_runner` (500-query retrieval ≈ official_top). Run the
full benchmark on a machine with more RAM/GPU.

## Informal / typo queries miss
**Fix:** the normalizer (`app/rag/query_normalizer.py`) handles slang/abbreviations/typos
before retrieval. Validate with `python -m app.evaluation.typo_benchmark`.
