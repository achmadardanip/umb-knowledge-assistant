"""RAG-eval API: start a run, list/inspect runs, and stream live progress over SSE."""
from __future__ import annotations

import asyncio
import json
import queue

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db, get_session_local
from app.db.models import RagEvalResult, RagEvalRun
from pydantic import BaseModel, Field

from app.evaluation import rag_eval_runner

router = APIRouter(prefix="/eval/rag", tags=["rag-eval"])


class AdhocRequest(BaseModel):
    question: str = Field(min_length=1)
    answer_model: str | None = None   # optional brain override


def _adhoc_payload(question, answer, context, sources, not_found, faith, rel) -> dict:
    """Assemble the ad-hoc single-question eval response (faithfulness skipped on refusal)."""
    return {
        "question": question,
        "answer": answer,
        "context": context,
        "sources": sources,
        "not_found": not_found,
        "faithfulness": None if faith is None
        else {"score": faith.score, "passed": faith.passed, "reason": faith.reason},
        "relevance": {"score": rel.score, "passed": rel.passed, "reason": rel.reason},
    }


@router.post("/adhoc")
def adhoc_eval(req: AdhocRequest) -> dict:
    """Type-a-question: run it through the real retrieval+answer path and grade it live."""
    from app.core.config import get_settings
    from app.evaluation.benchmark import _retrieve
    from app.evaluation.rag_graders import grade_faithfulness, grade_relevance, ollama_chat_fn
    from app.ingestion.embedder import get_embedder
    from app.rag.answer_generator import generate_answer
    from app.rag.intent_classifier import classify_intent
    from app.retrieval.hybrid_retriever import HybridRetriever

    settings = get_settings()
    db = get_session_local()()
    try:
        retriever = HybridRetriever(db, root_domain=settings.allowed_domain, embedder=get_embedder())
        intent = classify_intent(req.question).intent
        contexts = _retrieve(retriever, db, req.question, intent, 5, "agent_hybrid", settings)
        payload = generate_answer(question=req.question, contexts=contexts,
                                  language="id", answer_model=req.answer_model)
    finally:
        db.close()

    answer = payload.get("answer") or ""
    not_found = bool(payload.get("not_found"))
    context_text = "\n\n".join((c.get("chunk_text") or "") for c in contexts)[:8000]
    chat_fn = ollama_chat_fn(temperature=0.0)
    faith = None if not_found else grade_faithfulness(req.question, context_text, answer, chat_fn=chat_fn)
    rel = grade_relevance(req.question, answer, chat_fn=chat_fn)
    return _adhoc_payload(req.question, answer, context_text,
                          payload.get("sources") or [], not_found, faith, rel)


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
    # Validate existence up front so a missing run returns HTTP 404 (not a 200 SSE).
    probe = get_session_local()()
    try:
        if not probe.get(RagEvalRun, run_id):
            raise HTTPException(status_code=404, detail="run not found")
    finally:
        probe.close()

    q = rag_eval_runner.subscribe(run_id)

    async def generator():
        session = get_session_local()()
        try:
            run = session.get(RagEvalRun, run_id)
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
                try:
                    event = await asyncio.to_thread(q.get, timeout=30)
                except queue.Empty:
                    # No event within the interval. Re-check run status from the DB so we
                    # never hang if the run ended without publishing (abnormal exit), and
                    # emit a heartbeat to detect client disconnects promptly.
                    s = get_session_local()()
                    try:
                        run = s.get(RagEvalRun, run_id)
                        if run and run.status != "running":
                            yield _sse("done", {"run_id": run_id, "status": run.status,
                                                "agg_faithfulness": run.agg_faithfulness,
                                                "agg_relevance": run.agg_relevance})
                            break
                    finally:
                        s.close()
                    yield _sse("ping", {})
                    continue
                yield _sse(event["event"], event["data"])
                if event["event"] in ("done", "error"):
                    break
        finally:
            rag_eval_runner.unsubscribe(run_id, q)

    return StreamingResponse(generator(), media_type="text/event-stream")
