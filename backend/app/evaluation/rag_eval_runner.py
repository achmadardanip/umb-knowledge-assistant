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
