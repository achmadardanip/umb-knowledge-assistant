# Phase 7 — STEP 1 Merge Validation + STEP 3 Discovery (with a plan-changing finding)

**Date:** 2026-06-16

## STEP 1 — Merge + post-merge validation ✅
- Merged `feat/phase6-p3-conversation-isolation` → `main` (`ec50b21`, --no-ff).
- **587 passed / 0 failed** (`pytest --ignore=test_qwen3_reranker.py`); the single excluded
  test is KI-001 (Windows paging/OOM, not a regression). No regressions.
- Migrations present + versioned (002–007 + base); 007 prune already applied to prod.
- Local-PostgreSQL mode verified by tests (6); Supabase compatibility = default path.
- Report: `reports/post_merge_validation.json`.

## STEP 3 — Official-domain discovery (Tavily Map, real, no DB writes)

`python -m app.discovery.domain_discovery` — `reports/domain_discovery_report.json`.

| Domain | Pages discovered (Map) |
|---|--:|
| pendaftaran.mercubuana.ac.id | 35 |
| sia.mercubuana.ac.id | 15 |
| support.mercubuana.ac.id | 12 |
| pmb.mercubuana.ac.id | 0 — Tavily Map returns **HTTP 400** (not mappable) |
| sso.mercubuana.ac.id | 0 |
| bti.mercubuana.ac.id | 0 |
| baa.mercubuana.ac.id | 0 |
| **total** | **62** (all scope-valid, 0 rejected) |

### Finding: the coverage targets are not attainable from these domains
The plan targets 500+/500+/300+/100+/300+/200+/300+ chunks (~2,200 pages). Reality:
**~62 public informational pages exist across all seven domains.** SIA / SSO / BTI / BAA
are **login-gated operational applications**, not content sites — they have almost no
public crawlable pages. PMB rejects the mapper outright (400). So the "insufficient
coverage" is a **content-availability reality, not a crawl-effort gap** — no amount of
crawling these specific subdomains yields hundreds of pages each.

### What CAN raise coverage (evidence from a search-discovery probe)
Tavily **Search** (vs Map) surfaces additional official, ingestible content the operational
subdomains don't expose — including **PDFs**, which the plan rightly prioritizes:
- `pendaftaran.mercubuana.ac.id/cara-pendaftaran`, `/informasi-beasiswa`
- `bti.mercubuana.ac.id/panduan`
- `mercubuana.ac.id/biro-kemahasiswaan/beasiswa`, `ditmawa.mercubuana.ac.id/beasiswa-2`
- `feb.mercubuana.ac.id/.../Pengumuman-KRS-…CAP.pdf`, `lib.mercubuana.ac.id/id/panduan/…`

So a realistic coverage strategy is **map (62) + search-driven discovery + PDF ingestion
across the broader `*.mercubuana.ac.id`** (main site, faculty subdomains, ditmawa, lib) —
likely a few hundred high-value pages, not thousands. The chunk *targets* should be revised
to match available official content.

## Decision gate (before STEP 4–6 ingestion)
1. **Targets unattainable as written** — revise to the real ceiling (map + search + PDFs,
   ~low hundreds of pages), or keep chasing the operational subdomains (diminishing returns)?
2. **Ingestion writes to the over-quota production Supabase** (16 GB / 5.5 GB). Even the
   small real volume (~62–few-hundred pages) writes there — proceed on Supabase, or run the
   ingestion under `LOCAL_POSTGRES_MODE`?
3. **GPU groundedness (STEP 9)** remains impossible on this CPU/OOM-prone box — defer to the
   GPU host (`CGCV_ENTAILMENT_MODE=nli GROUNDEDNESS_DECISION_ENABLED=true`).
