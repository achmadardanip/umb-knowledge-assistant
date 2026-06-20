# Gap Analysis (Phase 27.8)

Synthesis of the Phase-27 audits against a production/enterprise bar. Status today:
**PRODUCTION_CERTIFIED_V1** — the gaps below are about scale, security hardening, and
operational maturity, not core correctness (retrieval/entity/citation guarantees hold).

Severity: **Critical** (blocks non-localhost prod) · **High** · **Medium** · **Low**.

## Architecture gaps
| Sev | Gap | Direction |
|---|---|---|
| High | Session memory is in-process per worker | Back with `chat_memories` table (interface exists) |
| Medium | GraphRAG rebuilt in-memory per call | Cache the typed graph; invalidate on entity change |
| Low | No `response_model` typing on endpoints | Add Pydantic response schemas |

## Scalability gaps
| Sev | Gap | Direction |
|---|---|---|
| High | Multi-worker breaks session memory + in-process rate limiting | DB/Redis-backed memory + limiter |
| Medium | End-to-end `/chat` latency is CPU-bound (30–105 s) | GPU embedder/LLM or hosted inference |
| Low | Full `/chat` not load-tested at 100-way (hot paths are: 0 errors, p95 <100 ms) | GPU load profile |

## Monitoring gaps
| Sev | Gap | Direction |
|---|---|---|
| Medium | Poll-based dashboards; no metrics export | Prometheus exporter + Grafana + alerts |
| Medium | No alerting on crawl failures / stale spikes / missing embeddings | Wire `/system/*` thresholds to alerts |
| Low | No request-id correlation / structured logs | Add correlation ids |

## Security gaps
| Sev | Gap | Direction |
|---|---|---|
| Critical | Admin/observability endpoints unauthenticated (`/system/*`, `/analytics`, `/crawl/*`, `/discovery/*`) | AuthN/Z or network isolation before non-localhost deploy |
| High | Sessions accessible by guessable `anonymous_session_id` | Bind to auth principal / signed tokens |
| Medium | CORS hard-coded to localhost; no security headers | Env-driven origins + CSP/HSTS |
| Low | In-process rate limiting; pgAdmin default creds | Redis limiter; lock down pgAdmin |

## UX gaps
| Sev | Gap | Direction |
|---|---|---|
| Medium | Minimal loading skeletons on dashboard/analytics; partial aria-labels; no `error.tsx` | Polish pass |
| Low | Polling cadence hard-coded; <360px viewport untested | Config + responsive QA |

## Documentation gaps (closed this phase)
| Sev | Gap | Status |
|---|---|---|
| — | README, architecture docs, audits, deployment checklist | **Done (Phase 27)** |
| Low | No API reference beyond `/docs` (OpenAPI) | Generate from OpenAPI |

## Operational gaps
| Sev | Gap | Direction |
|---|---|---|
| High | Crawler scheduler not wired to cron/systemd → not autonomous | OS scheduler + health alert |
| High | NLI groundedness certification pending ≥4 GB GPU (lexical CPU gate active) | Run on GPU host |
| Medium | No CI KB snapshot → full 913-test suite + retrieval benchmark can't fully run in CI | Publish seed/snapshot |
| Medium | Docker Desktop instability on dev host | Containerised CI / stable host |
| Low | Backups manual; retire legacy Supabase scripts | Scheduled backup + cleanup PR |

---

## Top 10 priorities after Phase 27
1. **Authenticate admin/observability endpoints** (`/system/*`, `/analytics`, `/crawl/*`, `/discovery/*`) — *Critical security*.
2. **Bind sessions to an auth principal** (replace guessable `anonymous_session_id`) — *High security*.
3. **DB/Redis-backed session memory + rate limiting** → enables multi-worker scale — *High scale*.
4. **Wire the crawler scheduler to cron/systemd** + failure alerting — *High operational*.
5. **GPU groundedness certification** (NLI) to close the lexical-tier gap — *High operational*.
6. **Publish a CI KB snapshot** so the 913-test suite + retrieval benchmark run green in Actions — *Medium*.
7. **Prometheus metrics export + alerts** (stale sources, missing embeddings, crawl failures) — *Medium monitoring*.
8. **Frontend polish**: loading skeletons, full aria-labels, `error.tsx`/`loading.tsx` — *Medium UX*.
9. **Backend cleanup**: `response_model` typing, remove retired Supabase scripts, consolidate entity alias maps — *Medium*.
10. **GPU end-to-end `/chat` load profile** + production origin/CORS/security-headers config — *Medium*.

All Phase-27 changes are documentation/audit/gitignore only — **no retrieval, GraphRAG, or
benchmark changes**; PRODUCTION_CERTIFIED_V1 metrics are unaffected.
