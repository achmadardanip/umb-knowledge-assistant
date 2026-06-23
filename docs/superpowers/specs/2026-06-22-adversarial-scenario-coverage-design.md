# Adversarial Scenario Coverage — Design

**Date:** 2026-06-22
**Status:** Approved (pending written-spec review)
**Owner:** Achmad Ardani Prasha
**Roadmap:** Sub-project #1 of the "expanded testing" set (then: multi-model audit,
export/share, direct question input, scoped red-teaming — each its own spec/plan/build).

## 1. Problem & Goal

The current monitoring scenarios (`scenarios.csv`, `golden_scenarios.csv`) are all
well-formed questions. Real users send **typo-laden, incomplete, mixed-language, and
ambiguous** questions. We want systematic **robustness coverage**: generate adversarial
variants of existing questions, tag each by perturbation type, and feed them into the same
Promptfoo monitoring eval so we can see how faithfulness/relevance hold up per perturbation.

**Goal:** A deterministic generator that turns base questions into tagged adversarial
variants (`typo`, `incomplete`, `mixed_lang`, `ambiguous`), wired into the existing eval,
with a `perturbation_type` column that is filterable in the Promptfoo viewer.

## 2. Decisions

1. **Programmatic generator** (deterministic, seeded) — not LLM-based (reproducible, fast,
   offline).
2. **Add a `perturbation_type` column** to scenario CSVs (`clean` for existing rows;
   `typo|incomplete|mixed_lang|ambiguous` for generated ones) so robustness is filterable.
3. Grading is **unchanged** — existing assertions (faithfulness, relevance, official-source)
   apply; the robustness signal is the pass-rate per `perturbation_type`. No new assertion.

## 3. Scope

### In scope
- `adversarial_scenarios.py` generator + unit tests.
- Generated `adversarial_scenarios.csv` (columns: `query, intent, perturbation_type, base_id`).
- Add `perturbation_type` column to `scenarios.csv` (all `clean`) and `golden_scenarios.csv`.
- Add `file://adversarial_scenarios.csv` to the monitoring config's `tests`.

### Out of scope
- LLM-based paraphrasing (rejected: non-deterministic).
- New assertions / a dedicated robustness metric (the `perturbation_type` var + existing
  pass/fail is enough; revisit later if needed).
- Changes to the grader, providers, or the 2-mode comparison.

## 4. Architecture & Components

```
data/golden_dataset/golden_dataset.jsonl   (base questions, source of truth)
        |  stratified, deterministic sample of N base questions
        v
adversarial_scenarios.py  (perturbation functions, seeded)
        |  per base question -> up to 4 tagged variants
        v
evaluation/promptfoo/adversarial_scenarios.csv   (query,intent,perturbation_type,base_id)
        +  scenarios.csv / golden_scenarios.csv gain a perturbation_type=clean column
        v
promptfooconfig.monitoring.yaml  tests: [scenarios.csv, golden_scenarios.csv, adversarial_scenarios.csv]
        v
Promptfoo eval -> viewer (filter by perturbation_type to read robustness per type)
```

Files:
| File | Responsibility |
|---|---|
| `backend/app/evaluation/adversarial_scenarios.py` | Pure perturbation functions + CSV writer + CLI |
| `backend/app/evaluation/tests/test_adversarial_scenarios.py` | Determinism + per-type behavior + tagging tests |
| `evaluation/promptfoo/adversarial_scenarios.csv` | Generated adversarial rows (committed) |
| `evaluation/promptfoo/scenarios.csv` | + `perturbation_type` column (`clean`) |
| `evaluation/promptfoo/golden_scenarios.csv` | + `perturbation_type` column (`clean`) |
| `evaluation/promptfoo/promptfooconfig.monitoring.yaml` | + adversarial CSV in `tests` |

## 5. Perturbation Methods (deterministic, no LLM)

All use a single `random.Random(seed)` for reproducibility. Each base question yields at
most one variant per type (skipped if a transform can't apply, e.g., too short to truncate).

- **`typo`** — pick a subset of words (seeded) and apply a character op (swap adjacent,
  drop, or duplicate a character). Leaves the question recognizable.
  `"Siapa dekan Fakultas Psikologi?"` → `"Siapa dekan Fakltas Psikolgi?"`
- **`incomplete`** — truncate to the first `k` words (k seeded within a range, min 2),
  dropping the trailing question/specifics.
  `"Siapa dekan Fakultas Psikologi UMB?"` → `"Siapa dekan Fakultas"`
- **`mixed_lang`** — replace a few common Indonesian tokens with English via a small fixed
  dictionary (e.g. `siapa→who`, `berapa→how much`, `biaya→cost`, `fakultas→faculty`,
  `jadwal→schedule`, `mahasiswa→student`, `bagaimana→how`).
  `"Siapa dekan Fakultas Psikologi?"` → `"Who dekan faculty Psikologi?"`
- **`ambiguous`** — strip the specific named entity/program/faculty/topic, leaving a vague
  pronoun-style question. Implemented by removing capitalized multi-word spans / known
  entity keywords and collapsing to a generic head.
  `"Siapa dekan Fakultas Psikologi?"` → `"Siapa dekannya?"`

Determinism: same input file + same seed ⇒ identical CSV (verified by a round-trip test).

## 6. Generator Interface

```
python -m app.evaluation.adversarial_scenarios \
  --base 20 \            # number of base questions sampled (stratified across intents)
  --types typo,incomplete,mixed_lang,ambiguous \
  --seed 20260622 \
  --out ../evaluation/promptfoo/adversarial_scenarios.csv
```
- Default `--base 20` → up to ~80 adversarial rows (skips when a transform can't apply).
- Reuses the stratified sampling idea from `rag_golden_subset.py` for base selection.
- Pure functions (`make_typo`, `make_incomplete`, `make_mixed_lang`, `make_ambiguous`,
  `perturb(question, seed)`), unit-tested without I/O.

## 7. Config Integration

`promptfooconfig.monitoring.yaml` `tests:` gains a third source:
```yaml
tests:
  - file://scenarios.csv
  - file://golden_scenarios.csv
  - file://adversarial_scenarios.csv
```
`perturbation_type` rides along as a Promptfoo var (extra CSV column), available for
filtering/grouping in the viewer. Note: adversarial rows run under both retrieval-mode
columns (indexed/hybrid), same as the rest.

## 8. Error Handling

| Case | Behaviour |
|---|---|
| Base question too short to truncate / no replaceable token | that perturbation type is skipped for that question (no empty rows) |
| Generated variant identical to base (no-op) | skipped (don't emit a "perturbation" that didn't change anything) |
| Missing golden_dataset.jsonl | generator errors with a clear message (matches existing module behavior) |

## 9. Testing (TDD)

- `make_typo` changes the string but keeps length within ±2 and is deterministic per seed.
- `make_incomplete` returns a strict prefix shorter than the original (≥2 words).
- `make_mixed_lang` replaces at least one known token when one is present; deterministic.
- `make_ambiguous` removes the specific entity and is shorter / more generic.
- `perturb()` / the CSV builder: tagging correct, `base_id` carried, no-op variants dropped,
  deterministic round-trip (same seed → identical rows).
- All unit tests run without the network, DB, or an LLM.

## 10. Risks & Mitigations

- **Over-aggressive perturbation makes nonsense** → keep transforms light (one char op per
  selected word; small replacement dictionary); the `clean` baseline stays for comparison.
- **Volume inflates run time** (each adversarial row × 2 retrieval modes) → default modest
  (~80 rows), parameterized; engineers scale `--base` deliberately.
- **`ambiguous` heuristic imperfect** → acceptable; it only needs to produce a vaguer
  question, not a perfect one; the `perturbation_type` tag makes mislabels visible.

## 11. Defaults

- `--base 20`, all four types, `--seed 20260622`.
- New column name: `perturbation_type`; baseline value `clean`.
