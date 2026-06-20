# Frontend Audit (Phase 27.5)

Scope: `frontend/app` (Next.js 16 App Router, React 19, TypeScript, Tailwind, shadcn/ui).
Method: `next build` (clean compile + typecheck), `tsc --noEmit` (clean), static grep scan.

## Build & typecheck
- `npm run build` → **✓ Compiled successfully**; routes `/`, `/dashboard`, `/analytics`, `/_not-found` prerendered.
- `tsc --noEmit` → **clean** (0 errors).
- **0** `console.log`/`debugger` statements; **0** `<img>` (icon-only UI via lucide → no alt-text gaps).
- Dark mode via next-themes + HSL CSS-var tokens (`globals.css`) — automatic; few explicit `dark:` classes is by design.

## Findings

### Critical
- None.

### High
- None. (Chat UX hardened across Phases 13–20: stop-generation, Esc-to-stop, double-submit
  guard, near-bottom auto-scroll, retry-without-losing-input, abort handling, memoized bubbles.)

### Medium
1. **Loading states are minimal on data panels.** `SystemDashboard` and `/analytics` render `—`
   placeholders while `react-query` fetches, rather than skeletons. → Add `Skeleton` for first paint.
2. **aria-label coverage is partial.** Only ~4 component files set `aria-label`; several icon-only
   buttons (dashboard toggles, sidebar actions) rely on `title` only. → Add `aria-label` to all icon buttons.
3. **No global error boundary / `error.tsx`.** A thrown render error in `/dashboard` or `/analytics`
   would surface the default Next overlay in dev and a blank route in prod. → Add `app/error.tsx`.

### Low
1. **One `any` usage** remains in a single file → tighten to a concrete type.
2. **Polling cadence** (30s dashboard, 8s session-context) is hard-coded → move to config.
3. **No `loading.tsx`** for route-level suspense fallbacks on `/dashboard` `/analytics`.
4. Mobile: chat uses a shadcn `Sheet` sidebar (good); dashboard/analytics grids are responsive
   (`md:`/`lg:` breakpoints) but untested on very small (<360px) viewports.

## Accessibility / responsiveness / dark mode
- Keyboard: Enter send · Shift+Enter newline · Esc stop — implemented.
- Dark mode: verified token-driven; freshness badges carry explicit dark variants.
- Responsiveness: dashboard/analytics use responsive grids; chat sidebar collapses to a Sheet.
- Hydration: all interactive components are `"use client"`; no server/client text mismatches observed in build.

## Recommendation
No release-blocking frontend issues. Address the Medium items (skeletons, aria-labels, error
boundary) in a follow-up polish pass.
