# Phase 6 · Priority 3 — Conversation-State Isolation

**Date:** 2026-06-16 · Scope confined to follow-up/memory isolation (no retrieval
redesign). Goal: a new-topic second question must not inherit the previous turn's
entity/topic context (the "Siapa dekan FASILKOM?" → "Bagaimana login SIA?" leak).

---

## What changed

### 1. Confidence-scored follow-up decision (`app/rag/intent_router.py`)
- New `FollowupDecision` dataclass + `analyze_followup(question, history)` returning
  `is_followup, confidence, cur_intent, prev_intent, intent_changed, topic_changed, reason`.
- `is_followup` is derived **solely** from `confidence >= FOLLOWUP_CONFIDENCE_THRESHOLD`
  (0.75) — the plan's `if followup_confidence < 0.75: start_new_context()`. The binary
  and the score can never disagree.
- `detect_followup()` is now a thin back-compat wrapper (all existing callers/tests unchanged).
- **Marker hardening:** split anaphora markers into STRONG (always a follow-up:
  `tersebut`, `bagaimana dengan`, `lebih detail`, `lainnya`, continuation prefixes `lalu/kalau/…`)
  vs WEAK (`ini`, `itu`, `nya`, …) that only signal continuation in a short, on-topic
  turn — because `ini`/`itu` are also determiners ("semester **ini**" = "this semester").

### 2. Intent/topic-aware context reset (`app/api/routes_chat.py`)
- `process_chat` now calls `analyze_followup`; on a new topic it resets **both** sides:
  - **retrieval** already used the bare question (v2) + the restored `history_conflicts`
    intent-drop;
  - **generation** now receives `conversation_history = history if is_followup else []`,
    so the LLM prompt no longer inherits prior turns on a topic switch (`start_new_context()`).
- The `followup_detection` step now emits `followup_confidence`, `intent_changed`,
  `topic_changed`, `reason`, `prev_intent`, `cur_intent` for observability.

### 3. Intent-detection fix (`app/rag/intent_router.py`)
- `detect_intent` now classifies UTS/UAS/`jadwal ujian`/`semester ini` questions as
  `academic_calendar` (was falling through to `general`). This was the root cause of
  the entire measured leak.

---

## Benchmark + evaluator (new)

- **`app/evaluation/followup_dataset.py`** → generates
  **`app/evaluation/followup_context_benchmark.json`**: **348 multi-turn conversations**
  grounded in REAL UMB faculties/programs/intents (not fabricated user data — that is the
  separate P1 golden dataset). Two families: (A) new-topic intent switches = the leakage
  test (240), (B/C) genuine anaphora follow-ups where context must be retained (108). Each
  conversation is deterministically labelled (`expected_followup`, `prior_terms`).
- **`app/evaluation/followup_eval.py`** → drives the REAL production functions
  (`analyze_followup` + `_build_retrieval_query` + `detect_retrieval_intent`), including an
  assistant turn carrying source hints, so every leakage vector (prior turn, chat title,
  prior source hints) is exercised. DB-free, deterministic.

### Results (`reports/followup_isolation_report.json`)

| Metric | Before fix | After fix | Target |
|---|--:|--:|--:|
| context_leakage_rate | 0.125 (30/240) | **0.000 (0/240)** | < 0.01 ✅ |
| followup_accuracy | 0.914 | **1.000** | > 0.95 ✅ |
| intent_switch_accuracy | 0.875 | **1.000** | — ✅ |

The benchmark **caught a real 12.5% leak** (all 30 from the mis-classified UTS question)
before it shipped — the value of the eval asset, not just the fix.

---

## Tests
- `test_intent_router.py` +4 P3 tests (structured decision fields, the UTS/`semester ini`
  regression, determiner-not-anaphora, and a guard that the 348-case benchmark stays at
  leakage < 1% / followup-acc > 95%). Existing 40 intent-router tests unchanged. Full
  backend suite re-run for regressions.

## Not in scope (per the directive / honesty)
- The plan's separate Topic/Entity/Intent "memories" are realized as the conversation-scoped
  context reset above; the long-term user-preference memory (`get_active_memories`) is a
  distinct feature and correctly persists across topics (it is not the leakage vector).
- 300+ AUTHENTIC user conversations from Telegram/call-center/chat-history are part of the
  P1 golden dataset (awaiting real data); this benchmark is a constructed, KB-grounded
  isolation test, clearly labelled as such.
