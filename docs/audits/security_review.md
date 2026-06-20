# Security Review (Phase 27.7)

Scope: backend API + frontend + config/secrets. Method: static scan + endpoint review.

## Good posture (verified)
- **No hardcoded secrets** in tracked files (scan clean); config via `os.getenv`; `.env`/`.env.*`
  gitignored with `.env.example` provided.
- **SQL injection: low risk** — queries use SQLAlchemy `text()` bind params or f-strings over
  *internal constants only* (table names), never raw user input.
- **XSS: mitigated** — answers render via `ReactMarkdown` + `rehypeSanitize`; no `dangerouslySetInnerHTML`.
- **Rate limiting + input length guards** on chat (`chat_guards`, `SlidingWindowRateLimiter`).
- **CORS** restricted to `http://localhost:3000` / `127.0.0.1:3000` (not wildcard).
- **Grounding guarantees** — official-source-only retrieval; unverified answers are refused (no source cards).

## Findings

### Critical
- None.

### High
1. **Admin/observability endpoints are unauthenticated.** `/system/*`, `/analytics`, `/crawl/*`,
   `/discovery/*`, `/stats`, and the `/dashboard` `/analytics` pages expose KB internals, failure
   analytics, and crawl state to anyone who can reach the API. → Put them behind authentication
   and/or a network policy (internal-only) before any non-localhost deployment.

### Medium
1. **Session access is by guessable `anonymous_session_id`.** `/sessions/{id}/messages` and
   `/sessions/{id}/context` are not bound to an authenticated owner — knowing/guessing an id exposes
   that conversation. → Bind sessions to an auth principal or use unguessable, signed session tokens.
2. **CORS origins are hard-coded to localhost.** Production origins must be configured (env-driven
   allowlist), and credentials handling reviewed.
3. **Rate limiting is in-process** — resets on restart and is per-worker, so limits are weaker across
   a multi-worker fleet. → Back with Redis (already a compose service) for shared counters.

### Low
1. No security headers middleware (CSP, X-Frame-Options, HSTS) on API/static responses.
2. pgAdmin in `docker-compose.local.yml` ships default creds (`admin@local.dev/admin`) — dev-only;
   never expose in prod.
3. No audit log of admin-endpoint access.

## Compliance with project guarantees
- Official UMB sources only · provenance preserved · citations enforced · no Supabase · no secrets committed — all upheld.

## Recommendation
Before any deployment beyond localhost, address the **High** (authenticate admin/observability
endpoints) and Medium #1 (session ownership) items. The data-grounding and injection/XSS posture is solid.
