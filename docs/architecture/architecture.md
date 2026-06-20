# Architecture Overview

## Purpose
The UMB Knowledge Assistant is a fully-local RAG system that answers UMB questions from
official sources only, with citations. This document is the entry point; each pipeline has
its own deep-dive doc in this folder.

## Flow
```
User → Next.js (chat/dashboard/analytics) → FastAPI (/chat, /chat/stream)
     → intent gate → [FAQ · Entity · GraphRAG · Vector] retrieval → reranker
     → answer generation + citation verification → response (answer + cited sources)
                              ↑
                     Session memory (per-session entities) resolves elliptical follow-ups
```

## Layers
| Layer | Module(s) | Responsibility |
|---|---|---|
| API | `app/api/routes_*.py`, `app/main.py` | HTTP/SSE endpoints, CORS, guards |
| Orchestration | `app/agent/umb_agent.py`, `app/api/routes_chat.py` | per-turn pipeline |
| Intent | `app/retrieval/intent_gate.py`, `app/rag/intent_router.py` | intent + follow-up classification, host gating |
| Structured | `app/retrieval/entity_retriever.py`, `app/graph/`, `app/retrieval/faq_retriever.py` | entity/graph/FAQ contexts |
| Vector | `app/retrieval/hybrid_retriever.py`, `app/ingestion/embedder.py` | keyword+dense (pgvector) fusion |
| Rank/Verify | `app/retrieval/reranker.py`, `app/rag/answer_generator.py`, `app/verification/` | ranking, citation/groundedness |
| Memory | `app/chat/session_memory.py`, `app/rag/followup_resolution.py` | conversation continuity |
| Data | `app/db/models.py`, PostgreSQL + pgvector | source of truth |
| Maintenance | `app/crawl/`, `app/ingestion/` | incremental crawl + ingestion |
| Observability | `app/api/routes_system.py`, `routes_analytics.py`, `app/evaluation/` | monitoring, eval |

## Key files
- `app/main.py` — app + router registration (38 routes).
- `app/api/routes_chat.py` — `process_chat` (the per-turn orchestration).
- `app/db/models.py` — SQLAlchemy schema (24 tables).

## APIs
Chat: `/chat`, `/chat/stream`, `/chat/prepare`, `/chat/finalize`. Sessions: `/sessions*`.
Observability: `/system/*`, `/crawl/*`, `/analytics`, `/stats`, `/health`. Feedback: `/feedback`.

## Risks
- In-process session memory (per-worker) limits horizontal scale.
- Local CPU embedder + LLM → high end-to-end chat latency (retrieval itself is fast).
- GraphRAG is in-memory (rebuilt per call) — cheap at current entity counts, revisit at scale.

## Future improvements
- DB-backed session memory; GPU groundedness; persisted graph cache; multi-worker deploy.
