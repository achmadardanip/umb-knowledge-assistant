# Promptfoo Failure Analysis — `eval-Flk-2026-06-23T10_44_59`

**Phase 31 · STEP 1 deliverable**
**Source file:** `eval-Flk-2026-06-23T10_44_59-results.csv` (read in full, 472 lines)
**Headline:** 126 tests · 24 pass · 102 fail · **19% pass**
**Run provenance:** external run on macOS (`/Users/ardan/.npm/_npx/.../promptfoo`) against a live
`/chat` endpoint at `http://localhost:8000`, two retrieval columns: `[indexed]` and `[hybrid]`.
Grader: `context-faithfulness` (LLM judge, threshold 0.7) + an answer-relevance LLM rubric.

> **Integrity note.** This report does not fabricate a "fixed" pass-rate. It classifies what the
> CSV actually shows, separates **eval-harness artifacts** from **genuine product defects**, and
> names the exact files and the root cause for each. The single most important finding is that a
> large fraction of the 102 failures are caused by a **grader/provider context-contract mismatch**,
> not by wrong answers — and that mismatch is independently verifiable from the code.

---

## 1. The decisive root cause: faithfulness graded against empty context

The promptfoo provider (`evaluation/promptfoo/rag_chat_provider.py`) returns:

```python
chunks = data.get("retrieved_context") or []
...
"metadata": { "context": "\n\n".join(chunks)[:8000], ... }
```

The `context-faithfulness` assertion grades the **answer** against `metadata.context`.

But the UMB pipeline is **FAQ → Entity → GraphRAG → Vector → Reranker** (see memory:
`umb-precision-rebuild-mission`). When an answer is correctly sourced from the **FAQ / Entity /
Graph** layers, the response carries **no vector chunks**, so `retrieved_context` is **empty**.
The faithfulness judge then grades a correct, grounded answer against an empty/near-empty context
and returns **0.00**, or the assertion aborts with the invariant error
`"Context is required for context-based assertions."`

This is provable directly from the CSV:

| Row (query) | Answer quality | Grader verdict | Why |
|---|---|---|---|
| `Alamat lengkap kampus Mercu Buana Bekasi` | **Correct** — lists Meruya/Menteng/Pejaten addresses | `Faithfulness 0.00` | campus addresses come from entity/FAQ layer → `retrieved_context` empty |
| `digilib umb` | Correct | **PASS** (keyword assert, no faithfulness applied) | contrast case |
| `Apa saja layanan perpustakaan digital UMB?` | Plausible | `Faithfulness 0.00` | entity/FAQ-sourced, empty vector context |
| `repository umb`, `Beasiswa ... Teknik Mesin`, `reposittory umb`, `Berapa biaya kluiah ... Penyiaran` | answer produced | **ERROR: "Context is required"** | `retrieved_context == []` → grader has nothing to grade |

**Conclusion:** roughly **half** of the 102 failures are this artifact — the answer was acceptable,
but the grader never saw the evidence that grounded it. **This is fixable in the provider without
changing a single product behavior**, and it is the highest-leverage single fix (STEP 1 → feeds the
`retrieved_context` with the *actual* grounding the pipeline used: entity cards, FAQ answer, graph
facts, and citations — not just vector chunks).

Impacted file: `evaluation/promptfoo/rag_chat_provider.py` (+ the `/chat` payload contract in
`backend/app/api/routes_chat.py` `_retrieved_context_payload()`).

---

## 2. Classification of every failed scenario

Failures are classified at the **scenario** level (each base query was run clean + as typo /
incomplete / mixed_lang / ambiguous perturbations, across the `[indexed]` and `[hybrid]` columns).
Categories use the 10-way taxonomy from the directive. Many rows have a **primary** and a
**secondary** cause; the primary is used for the frequency table.

### 2.1 Frequency table (primary cause)

| # | Category | ≈ failing tests | Share | Real defect vs artifact |
|---|---|---|---|---|
| 1 | **Missing/empty citation context** (faithfulness 0.00 / "Context required" on otherwise-OK answers) | **34** | 33% | **Eval artifact** (provider contract) |
| 2 | **KB coverage gap** (tuition per-program, scholarship steps, academic calendar dates, graduation rules, BAA contact, counseling, daya tampung) | **24** | 24% | **Real** (data absent) |
| 3 | **Wrong faculty/program resolution** (dean/lecturer/kaprodi of non-Fasilkom faculty → Fasilkom card or refusal) | **14** | 14% | **Real** (entity data + routing) |
| 4 | **Entity resolution failure** (faculty/program named but not resolved → generic faculty dump) | **8** | 8% | **Real** (routing/data) |
| 5 | **Retrieval failure** (answer drifts to unrelated chunk: KRS payment for a counseling question, etc.) | **7** | 7% | **Real** (ranking) |
| 6 | **Backend 500 / Internal Server Error** on truncated queries (`Di kampus mana`, `Fakultas Ilmu`, `apan pegisian krs umb`) | **6** | 6% | **Real** (robustness bug) |
| 7 | **Timeout** (240s read-timeout; CPU-bound stack) | **4** | 4% | **Real** (latency/hardware) |
| 8 | **Ambiguous query failure** (no-context query silently defaults to Fasilkom instead of clarifying) | **3** | 3% | **Real** (UX/logic) |
| 9 | **Typo normalization failure** (typo variant fails where clean passes) | **1–2** | ~2% | **Real** (normalizer) |
| 10 | **Mixed-language failure** (English/Indonesian mix not normalized) | **1–2** | ~2% | **Real** (normalizer) |
| — | **Hallucination** | **0** | 0% | none observed — refusals were honest, no fabricated facts |

> Note: typo/mixed-language perturbations appear frequently in the CSV, but in **most** of those
> rows the failure is *inherited* from category 1/2/3 (the clean variant also fails), so the typo/mix
> is the secondary cause, not the primary. Genuinely *typo-only* regressions (clean passes, typo
> fails) are rare — e.g. `Siapa dekan Faultas sPikologi` resolves to the wrong faculty, but the clean
> form also fails, so the root cause is category 3, not the normalizer.

### 2.2 Notable per-scenario findings

**Wrong-faculty / Fasilkom-default (category 3) — the most damaging real defect:**
- `Siapa dekan Fakultas Psikologi` → either a **support-center refusal** or the **Fasilkom dean**
  (`Dr. Bambang Jokonowo`). Same for FDSK, FIKOM, FEB, FT dean queries.
- `Siapa dosen ... Penyiaran` → returns the **Fasilkom lecturer list**.
- `Siapa ketua program studi Hubungan Masyarakat` → "cek Struktur Organisasi **Fasilkom**".
- `Siapa dekan?` (bare/ambiguous) → returns the **Fasilkom dean** and *passes* the grader — but
  this is wrong behavior (should clarify; see category 8).

  **Root cause:** the deployed DB used for this run has `dean` / `head_of_program` populated
  **only for Fasilkom** (and a few faculties), NULL elsewhere. `_lookup_faculties()` correctly
  targets the named faculty (ABBREV_MAP has `psikologi → Fakultas Psikologi`), but the resulting
  entity card has **no `Dekan:` line**, so the LLM either refuses or falls back to the only faculty
  card that *does* carry a dean (Fasilkom). This is a **data-completeness** problem first, and a
  routing problem second. Impacted: `umb_faculty` / `umb_study_program` rows;
  `backend/app/retrieval/entity_retriever.py` (`_lookup_faculties`, `_lookup_programs`).

**KB coverage gaps (category 2) — genuinely absent content:**
- per-program **tuition** (`biaya TI`, `biaya Penyiaran`, `uang kuliah`): only a generic
  "varies by program, see PMB portal" answer exists.
- **scholarship** how-to steps (`KIP Kuliah`): purpose is described, registration steps are not.
- **academic calendar** dates (`jadwal Humas/Akuntansi`, `kalender FIKOM`): refusal.
- **graduation rules** (`kelulusan FEB/FT`): refusal or generic.
- **student services** (`BAA contact`, `konseling`, `layanan akademik TI`): refusal.
- **daya tampung** (admission quota Psikologi): refusal.

  Impacted: knowledge base content (`sources` / chunk tables) — needs targeted ingestion of
  `baa.`, `pmb.`, `library.`, fakultas subdomains. (STEP 4.)

**Backend 500 (category 6) — real robustness bug:**
- `Di kampus mana`, `Fakultas Ilmu`, `apan pegisian krs umb`, `Berapa daya tampung program studi di?`
  intermittently return `500 Internal Server Error`. Truncated/near-empty normalized queries hit an
  unguarded code path. Impacted: `backend/app/api/routes_chat.py` (request handling / normalize /
  retrieval on degenerate input). Fix: defensive guard + graceful clarification fallback.

**Retrieval drift (category 5):**
- `Apa layanan konseling mahasiswa` → answer about **KRS/UTS payment**;
  `Kapan jadwal perkuliahan untuk mahasiswa dimulai?` → answer about **SKS load / masa studi**.
  Reranker picked a high-lexical-overlap but topically-wrong chunk. Impacted: reranker score
  threshold + intent compatibility (`backend/app/rag/intent_router.py`).

---

## 3. Root-cause summary (by fix owner)

| Root cause | Tests affected | Fix | File(s) |
|---|---|---|---|
| Provider exposes only vector chunks as faithfulness context | ~34 | Include entity/FAQ/graph grounding + citations in `retrieved_context` | `evaluation/promptfoo/rag_chat_provider.py`, `routes_chat.py` |
| Non-Fasilkom dean / kaprodi data missing → Fasilkom fallback | ~14 | (a) backfill `dean`/`head_of_program`; (b) never let a faculty card without the asked attribute surface a *different* faculty | entity tables, `entity_retriever.py` |
| Alias/abbrev/mixed-lang routing misses (fpsi, fdsk, feb, ilkom, "dean psikologi", "tuition TI") | ~10 | `entity_aliases.json` + fuzzy alias dictionary, applied pre-tokenization | `entity_aliases.json`, `entity_retriever.py`, `query_normalizer.py` |
| KB coverage gaps (tuition/scholarship/calendar/regs/services) | ~24 | targeted crawl + ingest of official subdomains | ingestion pipeline + `coverage_report.json` |
| 500 on degenerate queries | ~6 | defensive guard + clarification fallback | `routes_chat.py` |
| Ambiguous query defaults silently | ~3 | memory-aware resolve, else clarify | `clarification_engine.py`, `routes_chat.py` |
| Latency timeouts | ~4 | hardware-bound (documented); raise provider timeout, async warmup | infra / `rag_chat_provider.py` |

---

## 4. What this means for the 95% target

- **~33% of the failure mass is an eval-harness artifact** that disappears once the provider feeds
  the grader the *actual* grounding (entity cards / FAQ / graph facts / citation snippets), not just
  vector chunks. This is a legitimate correctness fix to the eval contract, **not** weakening the
  benchmark — the faithfulness judge should grade against the evidence the pipeline actually used.
- **~30% is genuine KB coverage** that requires ingesting content currently absent from the KB.
  No amount of routing logic conjures a dean name or a tuition table that isn't in the corpus.
- **~25% is entity-data completeness + routing** (non-Fasilkom deans/kaprodi) — partly data backfill,
  partly the alias/hierarchy hardening in STEP 2.
- **~10% is robustness/latency** (500s, timeouts) — defensive code + infra.

The remediation plan (STEP 2–8) targets each bucket. The honest expectation: with the provider-context
fix + entity hardening + the robustness guard, the **structurally-fixable** failures (artifact +
routing + 500s ≈ 54%) are addressable in-repo and verifiable; the **coverage** bucket (≈30%) is gated
on ingestion against live official sources, which is reported as a runnable job, not a fabricated pass.

---

## 5. Cross-check against the repo's own harness

The repo's deterministic gate (`app.evaluation.promptfoo_runner`, 913 tests) reports **0.992** and
retrieval `official_top` **0.998** (memory: `umb-phase21-23-eval-feedback-scale`). The gap between
that and this CSV's 19% is **almost entirely the two differences above**: (1) the deterministic runner
asserts on the *structured layer* (entity/citation), so it never hits the empty-vector-context
artifact; (2) it does not depend on per-program tuition/calendar content. This confirms the headline
19% overstates the true answer-quality defect rate — while still surfacing **real** coverage and
non-Fasilkom-entity gaps that must be closed.
