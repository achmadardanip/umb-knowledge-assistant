# Phase 27–29 Final Report — UX Hardening, Knowledge Expansion, Retrieval Intelligence

> Status: **all code/file deliverables implemented in the working tree.** Benchmark
> execution + git commit/push were blocked at report time by a temporary harness
> command-execution outage (read/write tools worked; command classification did not).
> Run the validation commands below to populate the actuals and push.

## Deliverables implemented

### P27.1 — Dark mode accessibility
- `tailwind.config.ts`: legacy tokens `ink/panel/line/brand` remapped to CSS vars (prior phase).
- 9 components fixed: `bg-white→bg-card`/`bg-popover`, `bg-skysoft text-ink→bg-accent text-accent-foreground`,
  `text-neutral-*→text-muted-foreground/foreground` — ProviderSelector, MemoryIndicator,
  ChatHistoryItem (active-state bug), MessageBubble (drawer+menu), Delete/RenameChatDialog,
  ExamplePrompts, SourceCard, ThinkingSteps. Doc: `docs/audits/dark_mode_audit.md`.

### P27.2 — Session history bug (one session = one history)
- **Frontend** (`ChatWidget.tsx`): adopt the authoritative `result.session_id` after each
  response, so a stale/unknown client id no longer spawns a new history per prompt.
- **Backend** (`_ensure_session`): unknown session id → create a fresh session (no 404).
- **Regression test** `app/tests/test_session_history.py`: 50-turn convo = exactly 1 history.

### P27.3 — Typo robustness engine
- `app/rag/query_normalizer.py`: slang/abbreviation expansion + stdlib-`difflib` fuzzy
  spell-correction (optional rapidfuzz) + filler removal. Wired into the chat retrieval path
  (`routes_chat`), idempotent on clean text (benchmarks unaffected).
- `app/evaluation/typo_benchmark.py`: 5/10/20% typo rates, with vs without normalization.

### P28 — Hybrid knowledge expansion
- P28.1 Tavily fallback: already present (`UMBLiveWebRetriever`/`TavilyClient` via agent
  web/hybrid mode); trusted-domain + citations + timestamps. Needs `TAVILY_API_KEY`.
- P28.2 `app/ingestion/knowledge_ingestion_pipeline.py`: gate(trusted+relevance+dedup) →
  clean → chunk → embed → insert → provenance → freshness → crawl_registry.
- P28.3 full re-crawl: framework ready (`crawler_scheduler`); needs live network. Doc:
  `docs/knowledge_expansion.md`.

### P29 — Evaluation + docs
- `app/evaluation/campus_random_query_benchmark.py`: 1000 informal/slang/typo/follow-up queries.
- `SETUP_GUIDE.md` (15-min zero-to-running) + `TROUBLESHOOTING.md` (every real issue we hit);
  README already refactored (no Supabase/legacy commands).

## Validation commands (run, then fill the table + push)
```bash
cd backend
export LOCAL_POSTGRES_MODE=true LOCAL_POSTGRES_URL=postgresql://umb:umb@localhost:5433/umb
# new
python -m app.evaluation.typo_benchmark
python -m app.evaluation.campus_random_query_benchmark
python -m pytest app/tests/test_session_history.py -q
# no-regression (must hold)
python -m app.evaluation.entity_benchmark
python -m app.evaluation.faculty_disambiguation_benchmark
python -m app.evaluation.followup_benchmark_v2
python -m app.evaluation.promptfoo_runner       # retrieval 500-q == official_top
cd ../frontend && npm run build                  # tsc + dark-mode parity
```

## Before vs after (targets; fill actuals after running)
| Metric | Required | Source |
|---|---|---|
| official_top | ≥ 0.998 (no regression) | promptfoo retrieval 500-q |
| citation_failure | ≤ 0.01 | benchmark / promptfoo |
| entity_accuracy | = 100% | entity_benchmark |
| followup_resolution | = 100% | followup_benchmark_v2 |
| context_retention | = 100% | followup_benchmark_v2 |
| faculty_leakage | = 0 | faculty_disambiguation |
| typo benchmark | ≥ 95% | typo_benchmark (NEW) |
| random-query accuracy | ≥ 95% | campus_random_query_benchmark (NEW) |

> Expectation: the entity/retrieval/faculty/followup suites are **unchanged** because the
> normalizer is applied only to the live chat query (benchmarks call the retriever directly),
> and the session/dark-mode changes don't touch retrieval. No-regression by construction; the
> commands above confirm it.

## Remaining risks (honest)
- P28.1/P28.3 require `TAVILY_API_KEY` + live network — not exercised in this offline env.
- `benchmark.py` (501-q + generation) segfaults on this memory-constrained host; use
  `promptfoo_runner` (500-q retrieval) as the official_top proxy.
- Admin/observability endpoints still unauthenticated (pre-existing; see GAP_ANALYSIS).
- Typo fuzzy threshold (0.82) is conservative; very heavy noise (>20%) may under-correct.
