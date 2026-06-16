# Phase 7 — Final Report (Coverage Expansion · Combined KB · Benchmark)

**Date:** 2026-06-16 · All work local / official-source only; production Supabase reads
for the one-time export only (no prod writes).

## 1. Coverage before vs after
- **Discovery reality (STEP 3):** Tavily Map of the 7 priority subdomains found only
  **62 public pages** (pendaftaran 35, sia 15, support 12; pmb HTTP 400; sso/bti/baa 0).
  SIA/SSO/BTI/BAA are login-gated apps — the 500+/300+ chunk targets are **content-unattainable**
  from those subdomains. Realistic path = Map + Search + **PDFs** across `*.mercubuana.ac.id`.
- **Ingested (STEP 4–5, broadened):** 150 URLs → **115 ingested (95 HTML + 20 PDF), 0 failures**.
  - **+463 chunks (+367 from PDFs), +108 official sources.** 100% source-URL provenance.
  - Top hosts: baa 358 (kalender/pedoman PDFs — surfaced via Search despite empty Map), pendaftaran 37, feb 28.

## 2. New chunk / source counts (combined local KB)
| | Production | + Coverage | Combined |
|---|--:|--:|--:|
| chunks | 10,942 | +472 | **11,414** (target ≥11,405 ✅) |
| embeddings | — | — | 11,414 (0 missing) |
| PDF chunks | — | — | 2,392 |
| sources | 3,508 | +~42 | 3,550 |
`combined_kb_validation.json` (caveat: 73 orphan-source chunks = 0.6%, retain metadata hostname).

## 3. Data integrity (7A) + audit (7B)
- 0 missing embeddings (7 re-embedded), **100% provenance** (url/hostname/source_type/crawl_date/authority_tier),
  duplicate rate **0.21% (<5%)**, metadata allowlist fixed to retain `authority_tier`/`page_count`/`crawl_date`.
- Reports: `duplicate_analysis.json`, `pdf_inventory.json` (20 docs/368 chunks), `source_distribution.json`,
  `authority_distribution.json` (tier1 60, tier2 371, tier3 33, tier4 8).

## 4. Retrieval benchmark — combined KB vs Phase-6 baseline (501-Q agent)
| Metric | Phase-6 (10,942) | Combined (11,414) | Target | Status |
|---|--:|--:|--:|:--:|
| official_top@1 | 0.988 | **0.994** | ≥0.98 | ✅ |
| citation_failure_rate | 0.012 | **0.006** | ≤0.01 | ✅ |
| strict_answerability | 0.705 | 0.709 | — | ↑ |
| retrieval accuracy | 0.705 | 0.709 | — | ↑ |
| coverage (official) | 1.0 | 1.0 | — | = |
| FAQ / Entity / Graph / Vector hit | .236/.837/.629/.772 | **.234/.843/.607/.780** | — | ~ |
| intent routing accuracy | 0.782 | 0.784 | — | ↑ |
| follow-up accuracy / context leakage | 1.0 / 0.0 | **1.0 / 0.0** | ≥0.99 / <0.01 | ✅ |
| latency p50 / p95 (ms) | 676 / 1396 | **81 / 111** | <1000 | ✅ |

**The coverage expansion halved the citation-failure rate (0.012→0.006) and raised
official_top (0.988→0.994)**; local pgvector cut latency ~8× (no network round-trip).
`benchmark_combined.json`.

## 5. Groundedness comparison (Phase 8)
**Deferred — requires a GPU host.** On this CPU box the NLI verifier OOMs and the
generation tier exceeds Ollama's 180 s/question. The verifier + decision + metrics are
built, opt-in, and unit-tested (P4); `citation_alignment` is LLM-free. Run on GPU:
`CGCV_ENTAILMENT_MODE=nli GROUNDEDNESS_DECISION_ENABLED=true python -m app.evaluation.golden_validation --limit 50`.

## 6. Latency comparison
p50 676 ms (remote Supabase) → **81 ms (local pgvector)**. The production figure is
network-bound; structured-layer server time is ~100 ms.

## 7. Remaining gaps
- **Leadership/accreditation enrichment (7E):** dean/kaprodi still sparse — faculty pages
  don't expose "Dekan: X" in extractable form; needs Tavily-Extract of the specific
  `pimpinan`/`struktur-organisasi` pages (uncertain yield). Entity tables migrated intact (7 faculties, 20 programs).
- **GPU groundedness (Phase 8)** — see §5.
- **73 orphan-source chunks** (0.6%) from the staging migration — cosmetic; metadata intact.
- **Sync staged coverage → Supabase**: the 463 new chunks live only in local pgvector
  (per the LOCAL_POSTGRES_MODE choice). Sync up when ready (small write).

## 8. Recommended Phase 8 roadmap
1. GPU groundedness validation run (the only blocked target).
2. Targeted leadership-page Extract (pimpinan/struktur) to close dean/kaprodi gaps.
3. Sync the staged coverage content to Supabase (or adopt local-PG as primary).
4. Periodic PDF re-crawl of baa/pendaftaran (the high-yield PDF hosts).

## Success criteria status
official_top ≥0.98 ✅ (0.994) · citation_failure ≤0.01 ✅ (0.006) · followup ≥0.99 ✅ (1.0) ·
context_leakage <0.01 ✅ (0.0) · latency p50 <1s ✅ (81 ms) · groundedness/hallucination
⏳ (GPU) · PMB/SIA/SSO chunk targets ⚠️ content-unattainable (documented) · leadership
enrichment ⚠️ partial.
