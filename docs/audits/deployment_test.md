# Full Local Deployment Test (Phase 27.4)

Executed live on 2026-06-20 against the local stack (PostgreSQL :5433, backend :8010).

## Database — PASS
| Check | Result |
|---|---|
| PostgreSQL starts | ✓ (container `umb-postgres` Up) |
| pgvector available | ✓ **v0.8.2** |
| Counts valid | chunks **5,911**, embeddings **5,911** (0 missing), sources **3,066**, faculties **7**, programs **20** |
| DB size | 74 MB · 0 orphan chunks · 0 dangling graph edges |

## Backend — PASS (10/10 endpoints HTTP 200)
| Endpoint | Status |
|---|---|
| `/health` | 200 |
| `/stats` | 200 — `{chunks:5911, sources:3066, entities:48, faculties:7, programs:20}` |
| `/analytics` | 200 |
| `/system/health` | 200 — `{status:"ok", database:"up", chunks:5911}` |
| `/system/stats` | 200 |
| `/system/crawl` | 200 |
| `/system/freshness` | 200 |
| `/system/graph` | 200 — `{nodes:69, edges:73, dangling:0, duplicates:0}` |
| `/system/database` | 200 — `{database_size:"74 MB", missing_embeddings:0, orphan_chunks:0}` |
| `/crawl/status` | 200 |

## Frontend — PASS
| Check | Result |
|---|---|
| `npm run build` | ✓ Compiled successfully |
| Typecheck (`tsc --noEmit`) | ✓ clean |
| Production routes | `/`, `/dashboard`, `/analytics`, `/_not-found` prerendered |

## Functional verification
| Item | Result |
|---|---|
| Session memory | ✓ `session_memory_validation` all assertions pass (extraction, anaphora, scoping, TTL); retention 1.0 |
| Source drawer / freshness | ✓ component compiles; payload carries `freshness_*` + `authority_tier` |
| Production certification | ✓ **PRODUCTION_CERTIFIED_V1** (official_top 0.998, citation 0.0, entity 1.0, leakage 0, retention 1.0, followup 1.0) |

## Notes
- Backend ran on **:8010** (8000/8001 held by an unrelated inference/exporter container on this host).
- Chat page renders; full end-to-end answer generation is CPU-latency-bound (30–105 s) and not part of
  this endpoint smoke test — retrieval/session layers validated deterministically instead.

**Verdict: full local deployment validated — DB, backend, and frontend all start and serve correctly.**
