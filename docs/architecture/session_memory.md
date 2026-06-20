# Session Memory Pipeline

## Purpose
Remember the entities a conversation has established so elliptical follow-ups
("beliau menjabat sejak kapan?", "akreditasinya bagaimana?") resolve to the right subject
instead of being forgotten. Raised context retention 0.67 → 1.0.

## Flow
```
turn N:   process_chat → query_entities → remember(session_id, query, contexts)
            store: faculty / program / dean / kaprodi / accreditation_subject / service / topic
turn N+1 (follow-up): is_followup? → recall(session_id)
            → followup_resolution.resolve_followup: detect elliptical (anaphora / "-nya" suffix)
            → choose subject (dekan/beliau → faculty; else program if set; else faculty)
            → append "Konteks entitas: {subject}" to the retrieval query
```
Store: in-process **TTL (30 min) + LRU** singleton, scoped per `session_id`. Auto-expiring,
lightweight, no DB round-trip → the session-less retrieval benchmark is unaffected.

## Key files
- `app/chat/session_memory.py` — `SessionMemory`, `get_session_memory`, entity extraction.
- `app/rag/followup_resolution.py` — `is_elliptical`, `resolve_followup`, `enrich_query`.
- `app/api/routes_chat.py` — recall+enrich (before retrieval), remember (after).
- `app/api/routes_sessions.py` — `GET /sessions/{id}/context` (Session Knowledge Card).

## APIs
`GET /sessions/{session_id}/context` → remembered entities + session age.

## Benchmarks
- `followup_benchmark_v2` — context_retention **1.0**, followup_resolution **1.0**, 0 leakage (10/20/50 turns).
- `session_memory_validation` — extraction + anaphora + scoping + TTL expiry all pass.

## Risks
- **In-process per worker** — not shared across a multi-worker fleet (single-worker safe).
- 30-min TTL: very long idle conversations lose context (re-established on next explicit mention).

## Future improvements
- Back the store with the `chat_memories` table for multi-worker + persistence across restarts.
