# RAG Eval Live Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local-Ollama–graded faithfulness + answer-relevance evaluation over a curated golden slice, surfaced as a real-time in-app `/eval` dashboard.

**Architecture:** A custom Python runner runs inside the FastAPI process as a worker thread: per question it retrieves context (the certified `agent_hybrid` path), calls `generate_answer`, grades the answer with the local Ollama model, persists each result to Postgres, and publishes a progress event to in-memory subscriber queues that an SSE endpoint drains. A new Next.js `/eval` page POSTs to start a run and streams results via the existing `getReader` SSE pattern. Report-only; the deterministic promptfoo gate is untouched.

**Tech Stack:** FastAPI, SQLAlchemy (ORM, `Base.metadata.create_all`), local Ollama (`LocalOllamaProvider`), Next.js 16 / React 19 / TypeScript / Tailwind / shadcn-ui.

**Spec:** `docs/superpowers/specs/2026-06-22-promptfoo-rag-eval-live-dashboard-design.md`

**Environment for all backend commands:**
```bash
cd backend
export LOCAL_POSTGRES_MODE=true
export LOCAL_POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/umb
# run python via the venv: .venv/bin/python ; tests via .venv/bin/pytest
```

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/evaluation/rag_golden_subset.py` | Deterministic stratified sampler → `rag_golden.json` |
| `backend/app/evaluation/rag_graders.py` | Faithfulness + relevance rubrics, JSON parse, Ollama chat_fn (pure) |
| `backend/app/evaluation/rag_eval_runner.py` | Background orchestration, in-memory pub/sub, single-run guard |
| `backend/app/api/routes_rag_eval.py` | POST/GET runs + SSE stream |
| `backend/app/db/models.py` | + `RagEvalRun`, `RagEvalResult` |
| `backend/app/main.py` | register `routes_rag_eval.router` |
| `backend/app/evaluation/tests/test_rag_golden_subset.py` | sampler unit tests |
| `backend/app/evaluation/tests/test_rag_graders.py` | grader/parse unit tests (mocked LLM) |
| `evaluation/promptfoo/datasets/rag_golden.json` | committed ~40-Q slice |
| `frontend/app/eval/page.tsx` | live dashboard page |
| `frontend/app/lib/ragEval.ts` | eval API client + stream helper |

---

## Task 1: Golden subset sampler

**Files:**
- Create: `backend/app/evaluation/rag_golden_subset.py`
- Test: `backend/app/evaluation/tests/test_rag_golden_subset.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/app/evaluation/tests/test_rag_golden_subset.py
from app.evaluation.rag_golden_subset import stratified_sample

ROWS = [
    {"id": f"q{i}", "question": f"Q{i}",
     "intent": ["admissions", "tuition", "faculty"][i % 3],
     "answerable": True, "synthetic": False}
    for i in range(30)
]


def test_sample_is_deterministic():
    assert stratified_sample(ROWS, 9, seed=1) == stratified_sample(ROWS, 9, seed=1)


def test_sample_size_and_fields():
    s = stratified_sample(ROWS, 9)
    assert len(s) == 9
    assert all(set(r) == {"id", "question", "intent"} for r in s)


def test_sample_excludes_synthetic_and_unanswerable():
    rows = ROWS + [
        {"id": "x", "question": "x", "intent": "admissions", "answerable": False, "synthetic": False},
        {"id": "y", "question": "y", "intent": "admissions", "answerable": True, "synthetic": True},
    ]
    ids = {r["id"] for r in stratified_sample(rows, 30)}
    assert "x" not in ids and "y" not in ids


def test_sample_spreads_across_intents():
    s = stratified_sample(ROWS, 9)
    assert len({r["intent"] for r in s}) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_golden_subset.py -v`
Expected: FAIL — `ModuleNotFoundError: app.evaluation.rag_golden_subset`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/evaluation/rag_golden_subset.py
"""Deterministic stratified sampler over data/golden_dataset.jsonl for the RAG eval.

Selects authentic, answerable questions spread evenly across intents with a fixed seed,
and writes them to evaluation/promptfoo/datasets/rag_golden.json. Reproducible:
same input + seed => same slice.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_GOLDEN = _ROOT / "data" / "golden_dataset" / "golden_dataset.jsonl"
_OUT = _ROOT / "evaluation" / "promptfoo" / "datasets" / "rag_golden.json"
_SEED = 20260622


def load_golden(path: Path = _GOLDEN) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def stratified_sample(rows: list[dict], size: int, seed: int = _SEED) -> list[dict]:
    pool = [r for r in rows if r.get("answerable") and not r.get("synthetic")]
    by_intent: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_intent[r.get("intent") or "general"].append(r)
    rng = random.Random(seed)
    for items in by_intent.values():
        rng.shuffle(items)
    intents = sorted(by_intent)
    selected: list[dict] = []
    idx = 0
    while len(selected) < size and any(by_intent.values()):
        bucket = by_intent[intents[idx % len(intents)]]
        if bucket:
            r = bucket.pop()
            selected.append({"id": r["id"], "question": r["question"], "intent": r.get("intent") or "general"})
        idx += 1
        if idx > size * 100:
            break
    return selected[:size]


def build(size: int = 40) -> list[dict]:
    return stratified_sample(load_golden(), size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=40)
    ap.add_argument("--out", default=str(_OUT))
    args = ap.parse_args()
    rows = build(args.size)
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} questions -> {args.out}")


if __name__ == "__main__":
    main()
```

Also create `backend/app/evaluation/tests/__init__.py` if the `tests` dir does not already exist (empty file).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_golden_subset.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Generate the committed slice**

Run: `.venv/bin/python -m app.evaluation.rag_golden_subset --size 40`
Expected: `wrote 40 questions -> .../evaluation/promptfoo/datasets/rag_golden.json`

- [ ] **Step 6: Commit**

```bash
git add backend/app/evaluation/rag_golden_subset.py \
        backend/app/evaluation/tests/test_rag_golden_subset.py \
        backend/app/evaluation/tests/__init__.py \
        evaluation/promptfoo/datasets/rag_golden.json
git commit -m "feat(rag-eval): deterministic golden subset sampler + 40-Q slice"
```

---

## Task 2: Graders (faithfulness + relevance)

**Files:**
- Create: `backend/app/evaluation/rag_graders.py`
- Test: `backend/app/evaluation/tests/test_rag_graders.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/app/evaluation/tests/test_rag_graders.py
from app.evaluation.rag_graders import grade_faithfulness, grade_relevance


def test_faithfulness_parses_clean_json():
    fn = lambda m: '{"score": 1.0, "supported": ["a"], "unsupported": [], "reason": "ok"}'
    v = grade_faithfulness("q", "ctx", "ans", chat_fn=fn, threshold=0.8)
    assert v.score == 1.0 and v.passed is True and v.grader_error is False


def test_faithfulness_handles_fenced_json():
    fn = lambda m: "```json\n{\"score\": 0.5, \"reason\": \"half\"}\n```"
    v = grade_faithfulness("q", "c", "a", chat_fn=fn, threshold=0.8)
    assert v.score == 0.5 and v.passed is False


def test_faithfulness_grader_error_on_garbage():
    fn = lambda m: "not json at all"
    v = grade_faithfulness("q", "c", "a", chat_fn=fn)
    assert v.grader_error is True and v.score is None and v.passed is None


def test_faithfulness_clamps_out_of_range():
    fn = lambda m: '{"score": 1.4, "reason": "x"}'
    assert grade_faithfulness("q", "c", "a", chat_fn=fn).score == 1.0


def test_relevance_threshold_pass():
    fn = lambda m: '{"score": 0.7, "reason": "addresses"}'
    assert grade_relevance("q", "a", chat_fn=fn, threshold=0.7).passed is True


def test_relevance_grader_error():
    fn = lambda m: "{bad json"
    assert grade_relevance("q", "a", chat_fn=fn).grader_error is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_graders.py -v`
Expected: FAIL — `ModuleNotFoundError: app.evaluation.rag_graders`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/evaluation/rag_graders.py
"""LLM-graded RAG metrics — faithfulness + answer-relevance.

Each grader builds a strict JSON-only rubric, calls a chat function (the local Ollama
model in production), and parses the verdict. Pure and unit-testable: the LLM call is
injected via `chat_fn`. Defaults are read from env so thresholds/model are tunable.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Callable

GRADER_MODEL = os.getenv("RAG_EVAL_GRADER_MODEL", "qwen2.5:7b-instruct")
FAITHFULNESS_THRESHOLD = float(os.getenv("RAG_EVAL_FAITHFULNESS_THRESHOLD", "0.8"))
RELEVANCE_THRESHOLD = float(os.getenv("RAG_EVAL_RELEVANCE_THRESHOLD", "0.7"))

ChatFn = Callable[[list[dict]], str]


@dataclass
class FaithfulnessVerdict:
    score: float | None
    passed: bool | None
    reason: str
    grader_error: bool = False


@dataclass
class RelevanceVerdict:
    score: float | None
    passed: bool | None
    reason: str
    grader_error: bool = False


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("no JSON object found")
    return json.loads(match.group(0))


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


_FAITHFULNESS_PROMPT = (
    "You are a strict evaluator. Given a QUESTION, the retrieved CONTEXT, and an ANSWER, "
    "decide whether every factual claim in the ANSWER is supported by the CONTEXT. "
    "Respond with ONLY a JSON object: "
    '{{"score": <0..1 fraction of claims supported>, "supported": [], "unsupported": [], "reason": "<one sentence>"}}.\n\n'
    "QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}\n"
)

_RELEVANCE_PROMPT = (
    "You are a strict evaluator. Given a QUESTION and an ANSWER, rate how directly the "
    "ANSWER addresses the QUESTION (ignore factual correctness, judge relevance only). "
    'Respond with ONLY a JSON object: {{"score": <0..1>, "reason": "<one sentence>"}}.\n\n'
    "QUESTION:\n{question}\n\nANSWER:\n{answer}\n"
)


def grade_faithfulness(question, context, answer, *, chat_fn: ChatFn,
                       threshold: float = FAITHFULNESS_THRESHOLD) -> FaithfulnessVerdict:
    prompt = _FAITHFULNESS_PROMPT.format(question=question, context=context, answer=answer)
    try:
        data = _extract_json(chat_fn([{"role": "user", "content": prompt}]))
        score = _clamp(float(data["score"]))
        return FaithfulnessVerdict(score=score, passed=score >= threshold, reason=str(data.get("reason", "")))
    except Exception as exc:
        return FaithfulnessVerdict(score=None, passed=None, reason=f"grader_error: {exc}", grader_error=True)


def grade_relevance(question, answer, *, chat_fn: ChatFn,
                    threshold: float = RELEVANCE_THRESHOLD) -> RelevanceVerdict:
    prompt = _RELEVANCE_PROMPT.format(question=question, answer=answer)
    try:
        data = _extract_json(chat_fn([{"role": "user", "content": prompt}]))
        score = _clamp(float(data["score"]))
        return RelevanceVerdict(score=score, passed=score >= threshold, reason=str(data.get("reason", "")))
    except Exception as exc:
        return RelevanceVerdict(score=None, passed=None, reason=f"grader_error: {exc}", grader_error=True)


def ollama_chat_fn(temperature: float = 0.0) -> ChatFn:
    """Real chat_fn backed by the project's LocalOllamaProvider."""
    from app.llm.local_ollama_provider import LocalOllamaProvider

    provider = LocalOllamaProvider()

    def _call(messages: list[dict]) -> str:
        return provider.chat(messages, temperature=temperature).content

    return _call
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_graders.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/rag_graders.py backend/app/evaluation/tests/test_rag_graders.py
git commit -m "feat(rag-eval): faithfulness + relevance graders with mocked-LLM tests"
```

---

## Task 3: Database models

**Files:**
- Modify: `backend/app/db/models.py` (append two classes after `Feedback`)

- [ ] **Step 1: Append the models**

```python
# backend/app/db/models.py  (append near the other chat/eval tables)
class RagEvalRun(Base):
    __tablename__ = "rag_eval_runs"

    id = Column(GUID, primary_key=True, default=uuid_str)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), default=utcnow)
    finished_at = Column(DateTime(timezone=True))
    dataset_version = Column(String(50))
    grader_model = Column(String(200))
    n_total = Column(Integer, default=0)
    n_done = Column(Integer, default=0)
    agg_faithfulness = Column(Float)
    agg_relevance = Column(Float)
    n_not_found = Column(Integer, default=0)
    n_grader_error = Column(Integer, default=0)
    error = Column(Text)

    results = relationship("RagEvalResult", back_populates="run", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("status IN ('running','completed','failed')", name="ck_rag_eval_run_status"),
    )


class RagEvalResult(Base):
    __tablename__ = "rag_eval_results"

    id = Column(GUID, primary_key=True, default=uuid_str)
    run_id = Column(GUID, ForeignKey("rag_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(128))
    question = Column(Text, nullable=False)
    intent = Column(String(64))
    answer = Column(Text)
    context = Column(Text)
    faithfulness_score = Column(Float)
    faithfulness_pass = Column(Boolean)
    faithfulness_reason = Column(Text)
    relevance_score = Column(Float)
    relevance_pass = Column(Boolean)
    relevance_reason = Column(Text)
    not_found = Column(Boolean, default=False)
    grader_error = Column(Boolean, default=False)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    run = relationship("RagEvalRun", back_populates="results")
```

- [ ] **Step 2: Create the tables (bootstrap auto-creates new ORM tables)**

Run: `.venv/bin/python -m app.db.bootstrap_local`
Expected: log line `ORM tables created (checkfirst).`

- [ ] **Step 3: Verify the tables exist**

Run:
```bash
docker exec umb-postgres psql -U postgres -d umb -tA -c \
  "select table_name from information_schema.tables where table_name like 'rag_eval%' order by 1;"
```
Expected:
```
rag_eval_results
rag_eval_runs
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(rag-eval): RagEvalRun + RagEvalResult tables"
```

---

## Task 4: Background runner + pub/sub

**Files:**
- Create: `backend/app/evaluation/rag_eval_runner.py`
- Test: `backend/app/evaluation/tests/test_rag_eval_runner.py`

- [ ] **Step 1: Write the failing test (guard + slice loading, no DB/LLM)**

```python
# backend/app/evaluation/tests/test_rag_eval_runner.py
import pytest
from app.evaluation import rag_eval_runner as r


def test_start_run_rejects_when_active(monkeypatch):
    monkeypatch.setattr(r, "_active_run_id", "existing")
    with pytest.raises(RuntimeError, match="already in progress"):
        r.start_run()


def test_start_run_rejects_empty_slice(monkeypatch):
    monkeypatch.setattr(r, "_active_run_id", None)
    monkeypatch.setattr(r, "_load_slice", lambda: [])
    with pytest.raises(RuntimeError, match="empty"):
        r.start_run()


def test_subscribe_unsubscribe_roundtrip():
    q = r.subscribe("run-1")
    r._publish("run-1", {"event": "ping", "data": {}})
    assert q.get_nowait() == {"event": "ping", "data": {}}
    r.unsubscribe("run-1", q)
    r._publish("run-1", {"event": "ping", "data": {}})
    assert q.empty()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_eval_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: app.evaluation.rag_eval_runner`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/evaluation/rag_eval_runner.py
"""Background RAG-eval runner: retrieve -> generate -> grade -> persist + stream.

Runs inside the FastAPI process as a daemon thread (retrieval + LLM are blocking). Each
result row is persisted and an event published to in-memory subscriber queues drained by
the SSE endpoint. Only one run may be active at a time (the local LLM is single-instance).
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.db.database import get_session_local
from app.db.models import RagEvalResult, RagEvalRun, utcnow
from app.evaluation.rag_graders import GRADER_MODEL, grade_faithfulness, grade_relevance, ollama_chat_fn

_GOLDEN = Path(__file__).resolve().parents[3] / "evaluation" / "promptfoo" / "datasets" / "rag_golden.json"

_run_lock = threading.Lock()
_active_run_id: str | None = None
_subscribers: dict[str, list[queue.Queue]] = {}
_sub_lock = threading.Lock()


def is_running() -> bool:
    return _active_run_id is not None


def subscribe(run_id: str) -> "queue.Queue":
    q: queue.Queue = queue.Queue()
    with _sub_lock:
        _subscribers.setdefault(run_id, []).append(q)
    return q


def unsubscribe(run_id: str, q: "queue.Queue") -> None:
    with _sub_lock:
        subs = _subscribers.get(run_id, [])
        if q in subs:
            subs.remove(q)


def _publish(run_id: str, event: dict) -> None:
    with _sub_lock:
        for q in list(_subscribers.get(run_id, [])):
            q.put(event)


def _load_slice() -> list[dict]:
    if not _GOLDEN.exists():
        return []
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _answer_with_context(db, question: str, retriever, settings):
    from app.evaluation.benchmark import _retrieve
    from app.rag.answer_generator import generate_answer
    from app.rag.intent_classifier import classify_intent

    intent = classify_intent(question).intent
    contexts = _retrieve(retriever, db, question, intent, 5, "agent_hybrid", settings)
    payload = generate_answer(question=question, contexts=contexts, language="id")
    return payload, contexts


def _run_eval(run_id: str, rows: list[dict]) -> None:
    global _active_run_id
    settings = get_settings()
    db = get_session_local()()
    chat_fn = ollama_chat_fn(temperature=0.0)
    f_scores: list[float] = []
    r_scores: list[float] = []
    n_not_found = 0
    n_grader_error = 0
    try:
        from app.ingestion.embedder import get_embedder
        from app.retrieval.hybrid_retriever import HybridRetriever

        retriever = HybridRetriever(db, root_domain=settings.allowed_domain, embedder=get_embedder())
        for i, row in enumerate(rows, start=1):
            started = time.perf_counter()
            payload, contexts = _answer_with_context(db, row["question"], retriever, settings)
            answer = payload.get("answer") or ""
            not_found = bool(payload.get("not_found"))
            context_text = "\n\n".join((c.get("chunk_text") or "") for c in contexts)[:8000]

            if not_found:
                faith = None
                n_not_found += 1
            else:
                faith = grade_faithfulness(row["question"], context_text, answer, chat_fn=chat_fn)
            rel = grade_relevance(row["question"], answer, chat_fn=chat_fn)
            latency_ms = int((time.perf_counter() - started) * 1000)

            if faith and faith.score is not None:
                f_scores.append(faith.score)
            if rel.score is not None:
                r_scores.append(rel.score)
            row_grader_error = bool((faith and faith.grader_error) or rel.grader_error)
            if row_grader_error:
                n_grader_error += 1

            db.add(RagEvalResult(
                run_id=run_id, question_id=row.get("id"), question=row["question"], intent=row.get("intent"),
                answer=answer, context=context_text,
                faithfulness_score=faith.score if faith else None,
                faithfulness_pass=faith.passed if faith else None,
                faithfulness_reason=(faith.reason if faith else "skipped (not_found)"),
                relevance_score=rel.score, relevance_pass=rel.passed, relevance_reason=rel.reason,
                not_found=not_found, grader_error=row_grader_error, latency_ms=latency_ms,
            ))
            run = db.get(RagEvalRun, run_id)
            run.n_done = i
            run.agg_faithfulness = (sum(f_scores) / len(f_scores)) if f_scores else None
            run.agg_relevance = (sum(r_scores) / len(r_scores)) if r_scores else None
            run.n_not_found = n_not_found
            run.n_grader_error = n_grader_error
            db.commit()

            _publish(run_id, {"event": "result", "data": {
                "question_id": row.get("id"), "question": row["question"], "intent": row.get("intent"),
                "faithfulness_score": faith.score if faith else None,
                "faithfulness_pass": faith.passed if faith else None,
                "relevance_score": rel.score, "relevance_pass": rel.passed,
                "not_found": not_found, "grader_error": row_grader_error, "latency_ms": latency_ms,
                "n_done": i, "n_total": len(rows),
                "agg_faithfulness": run.agg_faithfulness, "agg_relevance": run.agg_relevance,
            }})

        run = db.get(RagEvalRun, run_id)
        run.status = "completed"
        run.finished_at = utcnow()
        db.commit()
        _publish(run_id, {"event": "done", "data": {
            "run_id": run_id, "status": "completed",
            "agg_faithfulness": run.agg_faithfulness, "agg_relevance": run.agg_relevance,
        }})
    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        run = db.get(RagEvalRun, run_id)
        if run:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = utcnow()
            db.commit()
        _publish(run_id, {"event": "error", "data": {"message": str(exc)}})
    finally:
        db.close()
        with _run_lock:
            _active_run_id = None


def start_run() -> str:
    global _active_run_id
    with _run_lock:
        if _active_run_id is not None:
            raise RuntimeError("a run is already in progress")
        rows = _load_slice()
        if not rows:
            raise RuntimeError("golden slice is empty; generate evaluation/promptfoo/datasets/rag_golden.json")
        db = get_session_local()()
        try:
            run = RagEvalRun(status="running", dataset_version="golden-v2",
                             grader_model=GRADER_MODEL, n_total=len(rows), n_done=0)
            db.add(run)
            db.commit()
            run_id = run.id
        finally:
            db.close()
        _active_run_id = run_id
    threading.Thread(target=_run_eval, args=(run_id, rows), daemon=True).start()
    return run_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest app/evaluation/tests/test_rag_eval_runner.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/evaluation/rag_eval_runner.py backend/app/evaluation/tests/test_rag_eval_runner.py
git commit -m "feat(rag-eval): background runner with single-run guard + pub/sub"
```

---

## Task 5: API routes + registration

**Files:**
- Create: `backend/app/api/routes_rag_eval.py`
- Modify: `backend/app/main.py` (add one `include_router`)

- [ ] **Step 1: Write the route module**

```python
# backend/app/api/routes_rag_eval.py
"""RAG-eval API: start a run, list/inspect runs, and stream live progress over SSE."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db, get_session_local
from app.db.models import RagEvalResult, RagEvalRun
from app.evaluation import rag_eval_runner

router = APIRouter(prefix="/eval/rag", tags=["rag-eval"])


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _run_summary(run: RagEvalRun) -> dict:
    return {
        "id": run.id, "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "dataset_version": run.dataset_version, "grader_model": run.grader_model,
        "n_total": run.n_total, "n_done": run.n_done,
        "agg_faithfulness": run.agg_faithfulness, "agg_relevance": run.agg_relevance,
        "n_not_found": run.n_not_found, "n_grader_error": run.n_grader_error, "error": run.error,
    }


def _result_row(x: RagEvalResult) -> dict:
    return {
        "question_id": x.question_id, "question": x.question, "intent": x.intent,
        "answer": x.answer, "context": x.context,
        "faithfulness_score": x.faithfulness_score, "faithfulness_pass": x.faithfulness_pass,
        "faithfulness_reason": x.faithfulness_reason,
        "relevance_score": x.relevance_score, "relevance_pass": x.relevance_pass,
        "relevance_reason": x.relevance_reason,
        "not_found": x.not_found, "grader_error": x.grader_error, "latency_ms": x.latency_ms,
    }


@router.post("/runs")
def start_rag_run() -> dict:
    try:
        return {"run_id": rag_eval_runner.start_run()}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs")
def list_rag_runs(db: Session = Depends(get_db)) -> list[dict]:
    runs = db.query(RagEvalRun).order_by(RagEvalRun.started_at.desc()).limit(50).all()
    return [_run_summary(r) for r in runs]


@router.get("/runs/{run_id}")
def get_rag_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(RagEvalRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    rows = (
        db.query(RagEvalResult)
        .filter(RagEvalResult.run_id == run_id)
        .order_by(RagEvalResult.created_at)
        .all()
    )
    return {**_run_summary(run), "results": [_result_row(x) for x in rows]}


@router.get("/runs/{run_id}/stream")
async def stream_rag_run(run_id: str):
    q = rag_eval_runner.subscribe(run_id)

    async def generator():
        session = get_session_local()()
        try:
            run = session.get(RagEvalRun, run_id)
            if not run:
                yield _sse("error", {"message": "run not found"})
                return
            for x in (
                session.query(RagEvalResult)
                .filter(RagEvalResult.run_id == run_id)
                .order_by(RagEvalResult.created_at)
                .all()
            ):
                yield _sse("result", _result_row(x))
            if run.status != "running":
                yield _sse("done", {"run_id": run_id, "status": run.status,
                                    "agg_faithfulness": run.agg_faithfulness,
                                    "agg_relevance": run.agg_relevance})
                return
        finally:
            session.close()
        try:
            while True:
                event = await asyncio.to_thread(q.get)
                yield _sse(event["event"], event["data"])
                if event["event"] in ("done", "error"):
                    break
        finally:
            rag_eval_runner.unsubscribe(run_id, q)

    return StreamingResponse(generator(), media_type="text/event-stream")
```

- [ ] **Step 2: Register the router in `app/main.py`**

Find the block of `app.include_router(...)` calls (around line 132-141) and add after `routes_analytics`:

```python
from app.api import routes_rag_eval  # add with the other route imports at top
...
app.include_router(routes_rag_eval.router)
```

- [ ] **Step 3: Verify the endpoints respond (backend must be running)**

Run:
```bash
curl -s -X POST http://localhost:8000/eval/rag/runs | head -c 200 ; echo
curl -s http://localhost:8000/eval/rag/runs | head -c 200 ; echo
```
Expected: POST returns `{"run_id":"..."}` (or `{"detail":"a run is already in progress"}` with 409 if one is active); GET returns a JSON array containing the run.

> Note: restart the backend (`uvicorn`) before this step so the new router + models load.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/routes_rag_eval.py backend/app/main.py
git commit -m "feat(rag-eval): start/list/get run endpoints + SSE stream"
```

---

## Task 6: Live smoke run (2 questions)

**Files:** none (verification only)

- [ ] **Step 1: Temporarily shrink the slice for a fast smoke**

Run: `.venv/bin/python -m app.evaluation.rag_golden_subset --size 2 --out /tmp/rag_golden_smoke.json`
Then copy it in: `cp /tmp/rag_golden_smoke.json ../evaluation/promptfoo/datasets/rag_golden.json`

- [ ] **Step 2: Ensure Ollama + backend are up, then start a run**

Run:
```bash
curl -s http://localhost:11434/api/tags >/dev/null && echo "ollama ok"
RID=$(curl -s -X POST http://localhost:8000/eval/rag/runs | python3 -c "import sys,json;print(json.load(sys.stdin)['run_id'])")
echo "run_id=$RID"
```
Expected: `ollama ok` and a `run_id`.

- [ ] **Step 3: Stream the run and watch it grade live**

Run: `curl -N http://localhost:8000/eval/rag/runs/$RID/stream`
Expected: `event: result` lines (one per question) then `event: done`. Each result has `faithfulness_score` / `relevance_score`.

- [ ] **Step 4: Confirm persistence**

Run: `curl -s http://localhost:8000/eval/rag/runs/$RID | python3 -m json.tool | head -40`
Expected: `status: completed`, `n_done: 2`, a `results` array of length 2.

- [ ] **Step 5: Restore the full 40-Q slice**

Run: `.venv/bin/python -m app.evaluation.rag_golden_subset --size 40`
(no commit — the committed slice is already the 40-Q version from Task 1)

---

## Task 7: Frontend live dashboard

**Files:**
- Create: `frontend/app/lib/ragEval.ts`
- Create: `frontend/app/eval/page.tsx`

- [ ] **Step 1: Write the API client + stream helper**

```typescript
// frontend/app/lib/ragEval.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RagResult {
  question_id: string;
  question: string;
  intent: string | null;
  faithfulness_score: number | null;
  faithfulness_pass: boolean | null;
  relevance_score: number | null;
  relevance_pass: boolean | null;
  not_found: boolean;
  grader_error: boolean;
  latency_ms: number | null;
  n_done?: number;
  n_total?: number;
  agg_faithfulness?: number | null;
  agg_relevance?: number | null;
}

export interface RagRunSummary {
  id: string;
  status: "running" | "completed" | "failed";
  n_total: number;
  n_done: number;
  agg_faithfulness: number | null;
  agg_relevance: number | null;
  grader_model: string | null;
  error: string | null;
}

export async function startRun(): Promise<string> {
  const res = await fetch(`${API_BASE}/eval/rag/runs`, { method: "POST" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Failed to start run (${res.status})`);
  }
  return (await res.json()).run_id as string;
}

export async function listRuns(): Promise<RagRunSummary[]> {
  const res = await fetch(`${API_BASE}/eval/rag/runs`);
  return res.ok ? res.json() : [];
}

// Streams SSE from /eval/rag/runs/{id}/stream using the same getReader pattern as api.ts.
export async function streamRun(
  runId: string,
  handlers: {
    onResult?: (r: RagResult) => void;
    onDone?: (d: RagResult) => void;
    onError?: (msg: string) => void;
    signal?: AbortSignal;
  }
): Promise<void> {
  const res = await fetch(`${API_BASE}/eval/rag/runs/${runId}/stream`, { signal: handlers.signal });
  if (!res.ok || !res.body) throw new Error(`Stream failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consume = (rawEvent: string) => {
    const lines = rawEvent.split(/\r?\n/);
    const event = lines.find((l) => l.startsWith("event:"))?.replace(/^event:\s*/, "").trim() || "message";
    const data = lines.filter((l) => l.startsWith("data:")).map((l) => l.replace(/^data:\s*/, "")).join("\n");
    if (!data) return;
    const parsed = JSON.parse(data);
    if (event === "result") handlers.onResult?.(parsed);
    if (event === "done") handlers.onDone?.(parsed);
    if (event === "error") handlers.onError?.(parsed.message || "stream error");
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) if (part.trim()) consume(part);
  }
}
```

- [ ] **Step 2: Write the page**

```tsx
// frontend/app/eval/page.tsx
"use client";

import { useCallback, useRef, useState } from "react";
import { RagResult, startRun, streamRun } from "../lib/ragEval";

export default function EvalPage() {
  const [status, setStatus] = useState<"idle" | "running" | "completed" | "failed">("idle");
  const [rows, setRows] = useState<RagResult[]>([]);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [agg, setAgg] = useState<{ f: number | null; r: number | null }>({ f: null, r: null });
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    setError(null);
    setRows([]);
    setProgress({ done: 0, total: 0 });
    setStatus("running");
    try {
      const runId = await startRun();
      abortRef.current = new AbortController();
      await streamRun(runId, {
        signal: abortRef.current.signal,
        onResult: (r) => {
          setRows((prev) => [...prev, r]);
          if (r.n_done && r.n_total) setProgress({ done: r.n_done, total: r.n_total });
          setAgg({ f: r.agg_faithfulness ?? null, r: r.agg_relevance ?? null });
        },
        onDone: (d) => {
          setAgg({ f: d.agg_faithfulness ?? null, r: d.agg_relevance ?? null });
          setStatus("completed");
        },
        onError: (msg) => {
          setError(msg);
          setStatus("failed");
        },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("failed");
    }
  }, []);

  const pct = progress.total ? Math.round((progress.done / progress.total) * 100) : 0;
  const fmt = (n: number | null | undefined) => (n == null ? "—" : n.toFixed(2));
  const badge = (pass: boolean | null) =>
    pass == null ? "bg-gray-200 text-gray-700" : pass ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800";

  return (
    <main className="p-6 max-w-5xl mx-auto space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">RAG Evaluation</h1>
          <p className="text-sm text-muted-foreground">Faithfulness + answer-relevance · local Ollama judge · report-only</p>
        </div>
        <button
          onClick={run}
          disabled={status === "running"}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
        >
          {status === "running" ? "Running…" : "Run evaluation"}
        </button>
      </header>

      {error && <div className="rounded-md bg-red-100 text-red-800 p-3 text-sm">{error}</div>}

      <section className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Progress</div>
          <div className="text-xl font-semibold">{progress.done}/{progress.total || "—"}</div>
          <div className="mt-2 h-2 w-full rounded bg-gray-200">
            <div className="h-2 rounded bg-primary transition-all" style={{ width: `${pct}%` }} />
          </div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Faithfulness (avg)</div>
          <div className="text-xl font-semibold">{fmt(agg.f)}</div>
        </div>
        <div className="rounded-lg border p-4">
          <div className="text-xs text-muted-foreground">Relevance (avg)</div>
          <div className="text-xl font-semibold">{fmt(agg.r)}</div>
        </div>
      </section>

      <section className="rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40">
            <tr className="text-left">
              <th className="p-3">Question</th>
              <th className="p-3">Intent</th>
              <th className="p-3">Faithful</th>
              <th className="p-3">Relevant</th>
              <th className="p-3">Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.question_id}-${i}`} className="border-b align-top">
                <td className="p-3">{r.question}</td>
                <td className="p-3">{r.intent ?? "—"}</td>
                <td className="p-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${badge(r.faithfulness_pass)}`}>
                    {r.not_found ? "n/a" : fmt(r.faithfulness_score)}
                  </span>
                </td>
                <td className="p-3">
                  <span className={`rounded px-2 py-0.5 text-xs ${badge(r.relevance_pass)}`}>{fmt(r.relevance_score)}</span>
                </td>
                <td className="p-3 text-xs text-muted-foreground">
                  {r.not_found ? "not_found " : ""}{r.grader_error ? "grader_error" : ""}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td className="p-4 text-muted-foreground" colSpan={5}>No results yet — start a run.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Verify the page compiles and renders**

Run: `cd frontend && npm run lint` (this project's lint is `tsc --noEmit`)
Expected: no TypeScript errors.
Then load `http://localhost:3000/eval` in a browser → page renders with a "Run evaluation" button and an empty table.

- [ ] **Step 4: Manual live verification**

With the 40-Q slice and Ollama up, click **Run evaluation**. Expected: rows append one-by-one, the progress bar advances, and the two aggregate cards update as grading proceeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/lib/ragEval.ts frontend/app/eval/page.tsx
git commit -m "feat(rag-eval): live /eval dashboard (SSE-streamed results)"
```

---

## Task 8: Full run + docs

**Files:**
- Modify: `README.md` (add a short "RAG Eval (live)" subsection under Promptfoo Evaluation)
- Modify: `.gitignore` (ignore `reports/promptfoo_rag_latest.json` if a JSON export is added later — optional)

- [ ] **Step 1: Run the full 40-Q eval from the dashboard (or API)**

Start a run via the page or `curl -s -X POST http://localhost:8000/eval/rag/runs`; let it finish (~20–60 min). Confirm the final `agg_faithfulness` is reported and per-row reasons are populated via `GET /eval/rag/runs/{id}`.

- [ ] **Step 2: Add a README subsection**

Under `## Promptfoo Evaluation`, append:

```markdown
### RAG Eval (live, model-graded)

Faithfulness + answer-relevance over a curated ~40-question golden slice, graded by the
local Ollama model and streamed to an in-app dashboard at **`/eval`**. Report-only (does
not gate). Regenerate the slice with `python -m app.evaluation.rag_golden_subset --size 40`;
start a run from the dashboard or `POST /eval/rag/runs`. Requires Ollama running and the KB
restored. The deterministic 913-test gate (`promptfoo_runner`) is unchanged.
```

- [ ] **Step 3: Run the full backend test suite to confirm no regressions**

Run: `.venv/bin/pytest app/evaluation/tests -v`
Expected: all RAG-eval unit tests pass (sampler + graders + runner).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(rag-eval): document the live /eval RAG dashboard"
```

---

## Self-Review Notes

- **Spec coverage:** metrics (faithfulness + relevance) → Task 2; local Ollama judge → `ollama_chat_fn` (Task 2); golden ~40 slice → Task 1; Postgres tables → Task 3; runner + single-run guard + pub/sub → Task 4; API + SSE → Task 5; live dashboard → Task 7; report-only / refusal handling / grader-error handling → Tasks 4-5-7; testing strategy → Tasks 1,2,4 (unit) + Task 6 (smoke); deterministic gate untouched → no edits to `promptfoo_runner`/`promptfooconfig.yaml`/`provider.py`.
- **CI structural validation** (spec §11): the sampler unit test + a well-formed `rag_golden.json` are the structural checks; wiring them into `.github/workflows/promptfoo.yml` is a one-line addition the executor may include with Task 8 if desired (kept out of the gating path).
- **Known minor race (acceptable, report-only):** a result row completed between SSE replay and live-subscribe could appear twice; the frontend keys rows by `question_id`+index and this does not affect persisted aggregates.
- **Type consistency:** `FaithfulnessVerdict`/`RelevanceVerdict` fields (`score`, `passed`, `reason`, `grader_error`) are used consistently across runner and tests; `RagResult`/`RagRunSummary` TS interfaces match the `_result_row`/`_run_summary` JSON shapes.
