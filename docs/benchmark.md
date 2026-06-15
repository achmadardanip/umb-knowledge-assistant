# UMB Answerability Benchmark (Phase 1)

A measured baseline of answer quality across the twelve university use-case
categories. The benchmark exists to **identify which knowledge domains are weak
before further development** — all subsequent phases (structured entities,
canonical FAQ, typed GraphRAG) are driven by its results, not by assumptions.

## Components

| File | Purpose |
|------|---------|
| `app/evaluation/benchmark_dataset.py` | Deterministic question generator (≥500 Qs), grounded in entities mined from the KB. |
| `app/evaluation/umb_benchmark.json` | The committed dataset (regenerate when the KB/entities change). |
| `app/evaluation/benchmark.py` | Two-tier runner + per-question records + category aggregates + weak-domain report. |
| `app/tests/test_benchmark.py` | Generator + runner tests. |

Reuses the existing `app/evaluation/metrics.py` (offline faithfulness/citation
via `LexicalEntailmentChecker` — same engine as the live CGCV gate) and the
`evaluate_rag` helpers, so groundedness measured offline matches what the gate
enforces online.

## Categories (12 answer-bearing + controls)

Admissions, Tuition, Scholarship, Faculties, Study Programs, Lecturers/Staff,
Academic Calendar, Academic Regulations, Student Services, Campus Information,
SIA, SSO. Plus control questions (`out_of_scope`, `private_credential`,
`unanswerable`) that **must be abstained on** — these measure hallucination and
abstention correctness. Question types: `direct`, `paraphrase`, `ambiguous`,
`multi_hop`.

## Two tiers (why)

Local generation is CPU-bound (~30–160 s/answer), so running 500+ questions
through the LLM is infeasible. The harness separates:

- **Tier A — retrieval (all questions, no LLM).** Answerability, retrieval
  accuracy (expected-source hit), citation quality (archive/forbidden at rank 1),
  coverage, latency, per category. This is the weak-domain diagnostic.
- **Tier B — generation (opt-in, stratified sample).** Runs the answer generator
  on retrieved contexts and scores groundedness / hallucination / faithfulness.
  Bounded by `--sample-per-category`.

## Running

Regenerate the dataset (after a KB refresh) — mine entities first, then generate:

```bash
cd backend
# 1) mine faculties/programs/campuses from the indexed KB -> data/reports/kb_entities.json
# 2) regenerate the dataset
PYTHONPATH=. .venv/Scripts/python.exe -m app.evaluation.benchmark_dataset \
  --entities ../data/reports/kb_entities.json
```

Retrieval tier over all questions (fast diagnostic; `dense` = one indexed
pgvector call, ~3 s/q on remote Supabase):

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m app.evaluation.benchmark \
  --strategy dense --top-k 5 --out ../data/reports/benchmark_report.json
```

Add the generation tier on a small stratified sample (LLM; slow):

```bash
PYTHONPATH=. .venv/Scripts/python.exe -m app.evaluation.benchmark \
  --strategy hybrid --with-generation --sample-per-category 1 \
  --out ../data/reports/benchmark_report_gen.json
```

`--strategy hybrid` mirrors the production retriever (keyword + dense) but is
~4× slower because keyword search runs unindexed `ILIKE '%term%'` scans over
every chunk (see Known issues).

## Output

Per-question records follow the requested schema:

```json
{"question":"...","category":"...","answerable":true,"grounded":true,
 "hallucinated":false,"retrieved_sources":["https://..."],"confidence":0.9,
 "latency_ms":3100}
```

Plus aggregate reports: answerability / retrieval accuracy / citation-failure
rate / groundedness / hallucination **by category**, `missing_knowledge_areas`
(categories below the answerability target), `retrieval_failures`,
`citation_failures`, and `targets_met` against the success criteria
(answerability > 0.90, groundedness > 0.95, faithfulness > 0.95,
hallucination < 0.02).

## Known issues surfaced by the benchmark

- **Keyword retrieval latency (~12 s/query).** `_keyword_search` issues unindexed
  `ILIKE '%term%'` scans over `chunks.chunk_text`. This dominates both the
  benchmark (hybrid) and live-chat retrieval. Fix: add a Postgres GIN trigram
  index (`pg_trgm`) on `chunk_text`, or move to full-text search. Tracked as a
  follow-up; the benchmark defaults to `dense` to stay runnable.
