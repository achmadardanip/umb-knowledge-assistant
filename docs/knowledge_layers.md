# UMB Structured Knowledge Layers (Phases 2–4)

The assistant answers factual, relational, and high-frequency questions through
deterministic layers that run **before** vector search, then falls back to hybrid
retrieval and live web. This raises precision and groundedness on the domains the
Phase-1 benchmark flagged weak (admissions, SIA, SSO, scholarships, student services).

## Retrieval pipeline order

```
FAQ (canonical) → Entity (tables) → Graph (typed relations) → Vector (hybrid) → Reranker
   score 12–14        score 7–10          score 9                              (reranker reorders vector only)
```

Structured contexts (FAQ + entity + typed-graph) are **pinned above** the vector
results: the cross-encoder reranker only reorders chunk/passage candidates, so a
curated answer can never be buried by a passage. Because a matched structured
context scores above `WEB_FALLBACK_MIN_SCORE`, the KB-first gate also skips the
live-web fallback for covered questions (fast + grounded).

## Phase 2 — Structured Entity Knowledge Layer

Relational tables for deterministic lookup of factual questions (dean,
accreditation, address, contact, programs):

| Table | Holds |
|-------|-------|
| `umb_faculties` | name, dean, accreditation, campus, website, contact |
| `umb_study_programs` | program, degree level, faculty, head, accreditation |
| `umb_campuses` | address, city, phone, coordinates, facilities |
| `umb_scholarships` | provider, eligibility, requirements, deadline |
| `umb_contacts` | office/unit, email, phone, whatsapp, service type |
| `umb_services` | service name, description, unit, url, category |

- **Models:** `app/db/models.py` (`UMB*`)
- **Migration:** `app/db/migrations/002_umb_entities.sql`
- **Extractor:** `app/ingestion/entity_extractor.py`
  - `--seed` inserts curated known-correct entities (confidence 0.85)
  - `--mine` enriches from indexed chunks (dean/accreditation/kaprodi/phone, confidence 0.65)
- **Retriever:** `app/retrieval/entity_retriever.py` — `query_entities(db, query)` does
  intent detection (faculty / program / campus / scholarship / contact / service)
  and returns context dicts scored 7–10 (high-confidence = 10).

```bash
cd backend
# apply migration 002 (or Base.metadata.create_all), then:
PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.entity_extractor --seed --mine \
  --out ../data/reports/entity_extract.json
```

## Phase 3 — Canonical FAQ Layer

Verified question/answer pairs with paraphrase aliases, matched first so
high-frequency questions return a grounded, citation-bearing answer deterministically.

`umb_faqs`: `canonical_question`, `normalized_question`, `answer`, `aliases[]`,
`category`, `intent`, `source_urls[]`, `source_confidence`, `is_active`.

- **Model:** `app/db/models.py` (`UMBFAQ`)
- **Migration:** `app/db/migrations/003_umb_faqs.sql`
- **Seeder + data:** `app/ingestion/faq_seed.py` (17 curated FAQs across the weak domains)
- **Retriever:** `app/retrieval/faq_retriever.py` — `match_faq(db, query)`

Matching is deterministic (no embedding): the query is normalized (lowercased,
question words + ubiquitous "umb/universitas/mercu/buana" stripped) and compared
to the canonical question + every alias.

- **Exact** normalized match → score **14.0**
- **Fuzzy**: Dice token overlap ≥ `0.62` → score **12.0**

Curated aliases compensate for the lack of semantic matching. Volatile facts
(exact tuition, deadlines) are answered by directing the user to the official
portal rather than stating a number that could go stale; every FAQ carries an
official `source_urls` for citation.

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.faq_seed \
  --out ../data/reports/faq_seed.json
```

## Phase 4 — Typed University GraphRAG

A typed property graph over the Phase-2 entity tables (distinct from the
co-occurrence `KnowledgeGraph` in `graph_index.py`, which stays). It answers
**relational and multi-hop** questions deterministically — "which programs does
Fakultas Teknik offer?", "which faculty offers Teknik Informatika?".

- **Typed nodes:** faculty, program, person, campus, facility, scholarship, contact, service.
- **Typed relations:** `FACULTY_HAS_PROGRAM`, `FACULTY_HAS_DEAN`, `PROGRAM_HAS_HEAD`,
  `PROGRAM_BELONGS_TO_FACULTY` (inverse), `CAMPUS_HAS_FACILITY`,
  `SCHOLARSHIP_AVAILABLE_FOR_PROGRAM`, `SERVICE_BELONGS_TO_UNIT`.

- **Structure:** `app/graph/typed_graph.py` (`TypedGraph`, `TypedNode`, `TypedEdge`,
  name/alias word-boundary matching, JSON round-trip).
- **Build + retrieval:** `app/graph/typed_graph_store.py`
  - `build_typed_graph_from_db(db)` reads the entity tables → typed graph.
  - `typed_expansion_contexts(query, graph)` matches the query's entities, walks
    typed relations, and synthesises relational-answer contexts (score 9.0,
    `source_type="graph"`).
- **CLI:** `app/graph/build_typed_graph.py` → `data/graph/umb_typed_graph.json`
  (mtime-cached load). Run after the entity extractor.

```bash
cd backend
PYTHONPATH=. .venv/Scripts/python.exe -m app.graph.build_typed_graph
```

The entity retriever's generic program/faculty dumps were tightened so the
precise typed-graph relation isn't crowded out (programs: direct lookups only;
`"teknik"` now targets Fakultas Teknik).

## Wiring

`app/agent/umb_agent.py`:
- `run_faq_lookup()`, `run_entity_lookup()`, `run_typed_graph_lookup()` run before
  retrieval; results are merged (FAQ → entity → graph → chunks) via
  `_merge_structured_contexts()` after `run_indexed()` (which assigns a fresh list).
- Final assembly splits `source_type in {faq, entity, graph}` from the rerankable
  vector contexts; structured stay pinned on top.

## Tests

- `app/tests/test_entity_retriever.py` — 32 tests
- `app/tests/test_faq_retriever.py` — 20 tests
- `app/tests/test_typed_graph.py` — 17 tests (structure, DB build, persistence, relational retrieval, agent)
