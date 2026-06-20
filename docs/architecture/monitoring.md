# Monitoring & Observability

## Purpose
Let an administrator spot any KB/retrieval/crawl/freshness/graph/database issue in seconds,
and learn from real conversations via feedback analytics.

## Flow
```
PostgreSQL (live) → /system/* + /analytics endpoints → React Query (30s refetch)
   /dashboard  : KB · Retrieval · Crawl · Freshness · Graph · Database panels
   /analytics  : feedback rates + top failure categories
```

## Key files
- `app/api/routes_system.py` — `/system/{health,stats,crawl,freshness,graph,database}`.
- `app/api/routes_crawl.py` — `/crawl/status`, `/crawl/recent`.
- `app/api/routes_analytics.py` — `/analytics` (rates + top failures).
- `app/api/routes_stats.py` — `/stats`.
- `frontend/app/dashboard/page.tsx`, `frontend/app/analytics/page.tsx`, `components/SystemDashboard.tsx`.

## APIs
| Endpoint | Returns |
|---|---|
| `/system/health` | status, db up, chunk count |
| `/system/stats` | chunks/sources/entities/faculties/programs |
| `/system/crawl` | pending/processed/skipped/failed URLs, cadence |
| `/system/freshness` | verified today / aging / stale / oldest |
| `/system/graph` | nodes/edges/orphans/duplicates |
| `/system/database` | size, embeddings, missing embeddings, orphan chunks |
| `/analytics` | total chats, positive/negative/unanswered/citation rates, top failures |

## Risks
- No external metrics export (Prometheus/Grafana) yet — dashboard is poll-based.
- Analytics depend on saved chat history; empty on a fresh DB.

## Future improvements
- Prometheus exporter + alert rules; per-intent success tracking; feedback-driven FAQ expansion.
