# Backend Audit (Phase 27.6)

Scope: `backend/app` (FastAPI, SQLAlchemy, Python 3.12). Method: import smoke (38 routes load),
`pytest` (95 test files; chat/intent suites green), static grep scan.

## Strengths
- **API organised by domain** (`routes_chat/sessions/system/crawl/analytics/...`), registered in `app/main.py`.
- **Rate limiting + input guards** present: `app/api/chat_guards.py` (`enforce_question_length`,
  `enforce_rate_limit`) over `app/core/rate_limit.SlidingWindowRateLimiter`.
- **Parameterised SQL** — `text()` with bind params or f-strings over *internal constants only*
  (table names), not user input. **0 bare `except:`**; **0 TODO/FIXME**.
- **Logging** in 42 modules; per-request DB session via `Depends(get_db)`.
- Graceful degradation on observability endpoints (`try/except → {"available": false}`).

## Findings

### Critical
- None.

### High
1. **No Pydantic `response_model` on any endpoint** (0/38). Responses are raw dicts — no output
   schema validation or typed OpenAPI response bodies. → Add `response_model` to public endpoints.

### Medium
1. **Dead code — retired Supabase migration scripts.** `app/db/local_to_supabase.py` and
   `app/db/supabase_to_local.py` remain after Supabase was fully retired. → Remove (kept this phase
   to avoid deleting code mid-audit; flagged for a dedicated cleanup PR).
2. **81 `except Exception:` blocks.** Several are intentional best-effort (freshness enrichment,
   session-memory `remember`, observability) but the broad catches can mask real errors. → Narrow
   exception types and log at `warning` where swallowing.
3. **Entity/faculty alias maps duplicated across ~8 modules** (`entity_retriever`, `session_memory`,
   `followup_resolution`, `clarification_engine`, `routes_chat`, benchmarks). → Consolidate into one
   `app/domain/umb_entities.py` constants module.
4. **Ingestion module sprawl** (24 modules incl. `firecrawl_*`, `tavily_*`, `phase7_coverage_ingest`).
   Some are one-shot/historical. → Triage into `active/` vs `legacy/`.

### Low
1. In-process `SessionMemory` singleton is per-worker (documented; multi-worker needs DB backing).
2. `chat_logs` / `rag_answer_cache` / `knowledge_discovery_cache` tables exist — confirm all are
   still written/read or mark deprecated.
3. No request-id / structured-logging correlation across a turn.

## Database usage
- Session-per-request (API) and session-per-worker (load test) — correct isolation.
- Migrations are SQL files (`app/db/migrations/*.sql`) + idempotent python migrators
  (`bootstrap_local`, `migrate_freshness`). No Alembic; acceptable for a single-DB local stack.

## Recommendation
No release-blocking backend issues. Prioritise: response models (High), then Supabase-script
removal + alias consolidation (Medium) in a cleanup PR.
