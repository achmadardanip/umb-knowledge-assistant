# .gitignore Audit Report (Phase 27.3)

## Summary
The repository's `.gitignore` already covered the major generated artifacts (`reports/`,
`**/reports/`, `__pycache__/`, `node_modules/`, `.next/`, `*.log`, `*.db`, env files,
`*_REPORT.md`, `PHASE*.md`, `VALIDATION*.md`, `AUDIT*.md`). Phase 27 added the remaining
patterns from the directive and removed three stray tracked artifacts.

## Tracked artifacts that should NOT have been tracked (fixed)
| File | Action |
|---|---|
| `LOCAL_PERSISTENCE_VALIDATION.md` | `git rm --cached` (generated validation doc) |
| `README_VALIDATION.md` | `git rm --cached` (generated validation doc) |
| `data/reports/index_completeness.json` | `git rm --cached` (generated report JSON) |

## Patterns added in Phase 27
```
tmp/  *.dump  *.bak  backups/
.claude/  .agents/  .cursor/  .memory/
*validation*.json  *audit*.json  *benchmark*.json  *summary*.json  data/reports/
*_VALIDATION.md  *_SUMMARY.md  *_AUDIT.md  SUMMARY*.md
# negations so permanent docs stay tracked:
!docs/  !docs/**  !GAP_ANALYSIS.md
```

## Verification — ignored artifacts (sampled, confirmed ignored)
- `reports/*.json`, `evaluation/promptfoo/reports/*.json` ✓
- `backups/*.dump` ✓ · `*.log` ✓ · `__pycache__/`, `.next/`, `node_modules/` ✓
- `.env`, `.env.*` (except `.env.example`) ✓

## Verification — intentionally tracked (confirmed NOT ignored)
- `README.md`, `DEPLOYMENT_CHECKLIST.md`, `GAP_ANALYSIS.md`
- `docs/architecture/*.md`, `docs/audits/*.md`
- `evaluation/promptfoo/datasets/*.json` (test fixtures — needed by CI + reproducibility)
- `evaluation/promptfoo/promptfooconfig.yaml`, `provider.py`, `assertions/checks.py`
- all `backend/app/**` and `frontend/app/**` source

## Decision note (honest)
The directive lists `*_AUDIT.md` / `*_VALIDATION.md` / `*_SUMMARY.md` as "generated
documentation" to ignore. Phase 27's audit **deliverables** share those names but are
**permanent documentation**, so a negation (`!docs/**`) re-includes everything under `docs/`.
Net effect: ephemeral generated reports at the repo root stay ignored; curated docs under
`docs/` are tracked. This favours implementation reality over a literal pattern that would
have discarded the very deliverables this phase produces.

## Cleanup recommendations (non-blocking)
- Keep generating per-phase reports under `reports/` (already ignored).
- Periodically prune `backups/` (retain the latest pre-change dump).
- Consider a pre-commit hook rejecting `*.dump`, `reports/*.json`, and `.env` additions.
