# Entity Resolution Pipeline

## Purpose
Deterministically resolve named entities (faculty / program / dean / kaprodi / accreditation /
campus / service) from the `umb_*` tables — fast, exact, and leakage-free (a FEB question
never returns FASILKOM).

## Flow
```
query → tokenize → match faculty terms / program keywords / phrases
  → _lookup_faculties (suppress generic dump on program-specific queries)
  → _lookup_programs (keyword map + phrase match against real program names)
  → intent-aware demotion (apply_entity_intent_compatibility)
  → query-aware tie-break:
        dekan/wakil dekan/fakultas → faculty
        kaprodi/ketua program studi → program
        bare named program ("akreditasi sistem informasi") → program
  → faculty-leakage guard: drop standalone faculty cards on a program query
  → top entity card (score 10.0) pinned above vector
```

## Key files
- `app/retrieval/entity_retriever.py` — `query_entities`, `_PROGRAM_NAME_MAP`, `_TYPE_PRIORITY`.
- `app/rag/intent_router.py` — `apply_entity_intent_compatibility`, `INTENT_LECTURER`.

## APIs
Internal (called by the agent). Validated by `/system/stats` counts.

## Benchmarks
- `entity_benchmark` — 634 queries @ **100%** type+name accuracy.
- `faculty_disambiguation_benchmark` — 156 cases @ **100%** resolution, **0 leakage**.

## Risks
- A few FIKOM programs (Penyiaran/Periklanan) can mis-resolve under deep follow-ups (~6 edges).
- Program-name phrase matching scans all programs per query (cheap at 20 programs).

## Future improvements
- Alias table for ambiguous program names; per-program embeddings for fuzzy matching.
