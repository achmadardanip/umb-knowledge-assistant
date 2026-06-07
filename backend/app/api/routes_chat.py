from __future__ import annotations

import json
from collections import Counter
from queue import Queue
from threading import Thread
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.umb_agent import RetrievalMode, run_umb_agent
from app.api.chat_guards import apply_chat_safeguards
from app.chat.memory_service import get_active_memories, refresh_session_memory
from app.chat.message_service import recent_messages, save_message
from app.chat.session_service import create_session, get_session, maybe_autotitle_session, maybe_refine_title_with_llm
from app.chat.summarizer import compact_context
from app.core.config import get_settings
from app.db.database import get_db, get_session_local
from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider
from app.rag.answer_cache import build_cache_key, get_cached_answer, store_cached_answer
from app.rag.answer_generator import generate_answer
from app.rag.guardrails import guardrail_response
from app.rag.intent_classifier import classify_intent
from app.rag.language import detect_language
from app.retrieval.hybrid_retriever import HybridRetriever
from app.web_search.tavily_client import WebSearchConfigurationError


router = APIRouter(tags=["chat"])


StepStatus = Literal["running", "done", "skipped", "error"]


class ChatRequest(BaseModel):
    session_id: str | None = None
    anonymous_session_id: str | None = None
    question: str = Field(min_length=1)
    top_k: int = 5
    provider_override: Literal["openrouter", "openai", "gemini", "anthropic", "hermes"] | None = None
    memory_enabled: bool = True
    regenerate_from_message_id: str | None = None
    retrieval_mode: RetrievalMode = "hybrid"
    language: str | None = None


def _ensure_session(db: Session, payload: ChatRequest):
    if payload.session_id:
        session = get_session(db, payload.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    return create_session(db, payload.anonymous_session_id)


def _provider_meta(provider_override: str | None) -> tuple[str, str]:
    provider = get_provider(provider_override)
    return provider.provider_name, provider.model


def _agent_step(step_id: str, label: str, status: StepStatus, detail: str | None = None, metadata: dict | None = None) -> dict:
    return {
        "id": step_id,
        "label": label,
        "status": status,
        "detail": detail,
        "metadata": metadata or {},
    }


def _build_retrieval_query(question: str, history: list[dict], chat_title: str | None = None) -> str:
    prior_messages = list(history or [])
    normalized_question = " ".join((question or "").split()).lower()
    for index in range(len(prior_messages) - 1, -1, -1):
        message = prior_messages[index]
        if message.get("role") == "user" and " ".join((message.get("content") or "").split()).lower() == normalized_question:
            prior_messages.pop(index)
            break

    recent_user_turns = [message.get("content", "") for message in prior_messages if message.get("role") == "user"][-3:]
    source_hints: list[str] = []
    for message in prior_messages[-4:]:
        for source in (message.get("sources") or [])[:3]:
            if not isinstance(source, dict):
                continue
            hint = " ".join(
                str(value)
                for value in [source.get("title"), source.get("hostname"), source.get("url")]
                if value
            )
            if hint and hint not in source_hints:
                source_hints.append(hint)

    parts = [question]
    if chat_title and chat_title != "New Chat":
        parts.append(f"Judul chat: {chat_title}")
    if recent_user_turns:
        parts.extend(["Konteks pertanyaan sebelumnya:", *recent_user_turns])
    if source_hints:
        parts.extend(["Sumber resmi yang pernah relevan:", *source_hints[:5]])
    return compact_context(parts, max_chars=1600)


def _context_summary(contexts: list[dict]) -> tuple[str, dict]:
    hosts = [context.get("hostname") for context in contexts if context.get("hostname")]
    source_types = [context.get("source_type") or "unknown" for context in contexts]
    host_counts = Counter(hosts)
    type_counts = Counter(source_types)
    top_hosts = [host for host, _count in host_counts.most_common(5)]
    detail = f"{len(contexts)} konteks ditemukan"
    if top_hosts:
        detail += f" dari {', '.join(top_hosts)}"
    return detail, {"hosts": dict(host_counts), "source_types": dict(type_counts), "top_hosts": top_hosts}


def _fallback_answer_for_language(language: str | None) -> str:
    if (language or "").lower().startswith("en"):
        return "I have not found official information related to that question in the available public Universitas Mercu Buana sources."
    return "Saya belum menemukan informasi resmi terkait pertanyaan tersebut pada sumber publik Universitas Mercu Buana yang tersedia."


def process_chat(payload: ChatRequest, db: Session, emit_step=None) -> dict:
    visible_steps: list[dict] = []
    settings = get_settings()

    def emit(step_id: str, label: str, status: StepStatus, detail: str | None = None, metadata: dict | None = None) -> None:
        step = _agent_step(step_id, label, status, detail, metadata)
        visible_steps.append(step)
        if emit_step:
            emit_step(step)

    emit("session", "Membuka sesi percakapan", "running")
    session = _ensure_session(db, payload)
    emit("session", "Membuka sesi percakapan", "done", f"Session {session.id}")

    emit("save_user", "Menyimpan pertanyaan pengguna", "running")
    save_message(db, session_id=session.id, role="user", content=payload.question)
    title = maybe_autotitle_session(db, session.id, payload.question)
    emit("save_user", "Menyimpan pertanyaan pengguna", "done", title)

    emit("history", "Memeriksa konteks percakapan", "running")
    history = recent_messages(db, session.id, limit=settings.chat_history_max_messages)
    emit("history", "Memeriksa konteks percakapan", "done", f"{len(history)} pesan terakhir digunakan")

    emit("language", "Mendeteksi bahasa pertanyaan", "running")
    language_detected = (payload.language or detect_language(payload.question)).strip().lower()
    emit("language", "Mendeteksi bahasa pertanyaan", "done", language_detected, {"language_detected": language_detected})

    emit("intent", "Mengklasifikasikan intent pertanyaan", "running")
    intent_result = classify_intent(payload.question, history)
    emit(
        "intent",
        "Mengklasifikasikan intent pertanyaan",
        "done",
        intent_result.reason,
        {"intent": intent_result.intent, "confidence": intent_result.confidence},
    )

    if intent_result.intent == "smalltalk":
        answer_text = (
            "Hello, I can help search official public information from Universitas Mercu Buana. Please ask about admissions, study programs, fees, SSO/SIA, library, or academic services."
            if language_detected.startswith("en")
            else "Halo, saya siap membantu mencari informasi publik resmi Universitas Mercu Buana. Silakan tanyakan topik seperti pendaftaran, program studi, biaya, SSO/SIA, perpustakaan, atau layanan akademik."
        )
        answer_payload = {
            "answer": answer_text,
            "sources": [],
            "confidence": "low",
            "not_found": False,
            "provider_used": "system",
            "model_used": "rule-based-intent",
            "memory_used": False,
        }
        emit("answer", "Menjawab sapaan tanpa provider AI", "done", "Tidak memakai RAG/LLM karena intent smalltalk")
        emit("save_answer", "Menyimpan jawaban dan metadata", "running")
        assistant = save_message(
            db,
            session_id=session.id,
            role="assistant",
            content=answer_payload["answer"],
            sources=[],
            confidence_score=answer_payload["confidence"],
            provider_used=answer_payload["provider_used"],
            model_used=answer_payload["model_used"],
            not_found=False,
            visible_steps=visible_steps,
            metadata={
                "memory_used": False,
                "intent": intent_result.intent,
                "retrieval_mode": payload.retrieval_mode,
                "language_detected": language_detected,
                "retrieved_context_count": 0,
                "prompt_context_chunk_count": 0,
                "indexed_context_count": 0,
                "web_context_count": 0,
                "agent_tool_calls": 0,
            },
        )
        emit("save_answer", "Menyimpan jawaban dan metadata", "done", f"Message {assistant.id}")
        assistant.visible_steps = visible_steps
        db.commit()
        return {
            "session_id": session.id,
            "message_id": assistant.id,
            **answer_payload,
            "chat_title": title,
            "visible_steps": visible_steps,
            "intent": intent_result.intent,
            "retrieval_mode": payload.retrieval_mode,
            "language_detected": language_detected,
            "retrieved_context_count": 0,
            "prompt_context_chunk_count": 0,
            "indexed_context_count": 0,
            "web_context_count": 0,
            "agent_tool_calls": 0,
        }

    emit("guardrail", "Memvalidasi keamanan pertanyaan", "running")
    blocked = guardrail_response(payload.question)
    if intent_result.intent == "unsafe_private_data" and not blocked:
        blocked = "Saya tidak dapat mengakses atau menampilkan data pribadi mahasiswa. Silakan gunakan kanal resmi Universitas Mercu Buana."
    if blocked:
        emit("guardrail", "Memvalidasi keamanan pertanyaan", "done", "Pertanyaan diblokir oleh guardrail")
        provider_used, model_used = "system", "guardrail"
        assistant = save_message(
            db,
            session_id=session.id,
            role="assistant",
            content=blocked,
            sources=[],
            confidence_score="low",
            provider_used=provider_used,
            model_used=model_used,
            not_found=True,
            visible_steps=visible_steps,
            metadata={
                "memory_used": False,
                "intent": intent_result.intent,
                "retrieval_mode": payload.retrieval_mode,
                "language_detected": language_detected,
                "retrieved_context_count": 0,
                "prompt_context_chunk_count": 0,
                "indexed_context_count": 0,
                "web_context_count": 0,
                "agent_tool_calls": 0,
            },
        )
        emit("save_answer", "Menyimpan jawaban dan metadata", "done", f"Message {assistant.id}")
        assistant.visible_steps = visible_steps
        db.commit()
        return {
            "session_id": session.id,
            "message_id": assistant.id,
            "answer": blocked,
            "sources": [],
            "confidence": "low",
            "not_found": True,
            "provider_used": provider_used,
            "model_used": model_used,
            "memory_used": False,
            "chat_title": title,
            "visible_steps": visible_steps,
            "intent": intent_result.intent,
            "retrieval_mode": payload.retrieval_mode,
            "language_detected": language_detected,
            "retrieved_context_count": 0,
            "prompt_context_chunk_count": 0,
            "indexed_context_count": 0,
            "web_context_count": 0,
            "agent_tool_calls": 0,
        }
    emit("guardrail", "Memvalidasi keamanan pertanyaan", "done", "Pertanyaan aman untuk diproses")

    retrieval_query = _build_retrieval_query(payload.question, history, title)
    top_k = max(1, min(payload.top_k or settings.rag_top_k_default, settings.rag_top_k_max))

    emit("memory", "Memeriksa memori chat yang relevan", "running")
    memories = []
    if payload.memory_enabled and session.memory_enabled:
        memories = [
            {"id": memory.id, "memory_type": memory.memory_type, "content": memory.content}
            for memory in get_active_memories(db, session.id, session.anonymous_session_id, limit=settings.memory_max_items)
        ]
        emit("memory", "Memeriksa memori chat yang relevan", "done", f"{len(memories)} memori aman ditemukan", {"memory_used": bool(memories)})
    else:
        emit("memory", "Memeriksa memori chat yang relevan", "skipped", "Memori dinonaktifkan untuk request ini")

    emit("contextualize", "Menyusun query retrieval kontekstual", "done", "Pertanyaan digabung dengan konteks percakapan aman")
    if intent_result.intent == "out_of_scope":
        emit("retrieval", "Mencari sumber resmi UMB", "skipped", "Intent di luar cakupan UMB")
        contexts = []
        agent_result = None
    else:
        emit("retrieval", "Mencari sumber resmi UMB", "running", f"Mode {payload.retrieval_mode}; top-k dibatasi ke {top_k} konteks relevan")
        try:
            agent_result = run_umb_agent(
                db=db,
                query=retrieval_query,
                retrieval_mode=payload.retrieval_mode,
                top_k=top_k,
                root_domain=settings.allowed_domain,
                emit=emit,
                indexed_retriever_cls=HybridRetriever,
            )
        except WebSearchConfigurationError as exc:
            db.rollback()
            emit("umb_live_web_search", "Mencari sumber live resmi UMB", "error", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        contexts = agent_result.contexts
    summary_detail, summary_metadata = _context_summary(contexts)
    emit("retrieval", "Mencari sumber resmi UMB", "done" if contexts else "skipped", summary_detail, summary_metadata)

    emit("provider", "Memilih provider AI", "running")
    provider_used, model_used = _provider_meta(payload.provider_override)
    emit("provider", "Memilih provider AI", "done", f"{provider_used} / {model_used}")

    if not contexts:
        emit("answer", "Menyusun jawaban fallback", "done", "Tidak ada konteks resmi yang cukup")
        answer_payload = {
            "answer": _fallback_answer_for_language(language_detected),
            "sources": [],
            "confidence": "low",
            "not_found": True,
            "provider_used": provider_used,
            "model_used": model_used,
            "memory_used": bool(memories),
        }
    else:
        try:
            cache_key = build_cache_key(
                question=payload.question,
                intent=intent_result.intent,
                provider_used=provider_used,
                model_used=model_used,
                contexts=contexts,
                memory_enabled=bool(memories),
            )
            emit("cache", "Memeriksa cache jawaban", "running")
            cache_enabled = settings.rag_answer_cache_enabled and (
                payload.retrieval_mode == "indexed" or settings.web_search_cache_answers
            )
            cached_payload = get_cached_answer(db, cache_key) if cache_enabled else None
            if cached_payload:
                answer_payload = cached_payload
                answer_payload["memory_used"] = bool(memories)
                emit("cache", "Memeriksa cache jawaban", "done", "Cache hit, provider AI tidak dipanggil")
                emit("answer", "Menggunakan jawaban cache berbasis sumber", "done")
            else:
                emit(
                    "cache",
                    "Memeriksa cache jawaban",
                    "skipped" if not cache_enabled else "done",
                    "Cache tidak aktif untuk mode live/hybrid" if not cache_enabled else "Cache miss",
                )
                emit("answer", "Menyusun jawaban berbasis sumber resmi", "running", f"Mengirim {len(contexts)} chunk relevan, bukan seluruh dokumen")
                answer_payload = generate_answer(
                    question=payload.question,
                    contexts=contexts,
                    recent_messages=history,
                    memories=memories,
                    provider_override=payload.provider_override,
                    language=language_detected,
                )
                if cache_enabled and not answer_payload.get("not_found"):
                    store_cached_answer(
                        db,
                        cache_key=cache_key,
                        question=payload.question,
                        intent=intent_result.intent,
                        provider_used=answer_payload.get("provider_used") or provider_used,
                        model_used=answer_payload.get("model_used") or model_used,
                        answer_payload=answer_payload,
                        ttl_seconds=settings.rag_answer_cache_ttl_seconds,
                    )
            emit(
                "citation",
                "Memvalidasi sumber dan sitasi",
                "done" if answer_payload.get("sources") else "skipped",
                f"{len(answer_payload.get('sources') or [])} sitasi valid",
                {"not_found": bool(answer_payload.get("not_found"))},
            )
        except ProviderConfigurationError as exc:
            db.rollback()
            emit("provider", "Memilih provider AI", "error", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    emit("save_answer", "Menyimpan jawaban dan metadata", "running")
    metadata = {
        "memory_used": bool(memories),
        "intent": intent_result.intent,
        "retrieval_mode": payload.retrieval_mode,
        "language_detected": language_detected,
        "retrieved_context_count": len(contexts),
        "prompt_context_chunk_count": min(len(contexts), top_k),
        "indexed_context_count": agent_result.indexed_context_count if agent_result else 0,
        "web_context_count": agent_result.web_context_count if agent_result else 0,
        "agent_tool_calls": agent_result.agent_tool_calls if agent_result else 0,
        "retrieval_fallback_used": agent_result.retrieval_fallback_used if agent_result else False,
        "retrieval_warnings": agent_result.retrieval_warnings if agent_result else [],
        "cache_hit": bool(answer_payload.get("cache_hit")),
        "regenerate_from_message_id": payload.regenerate_from_message_id,
    }
    assistant = save_message(
        db,
        session_id=session.id,
        role="assistant",
        content=answer_payload["answer"],
        sources=answer_payload.get("sources") or [],
        confidence_score=answer_payload.get("confidence"),
        provider_used=answer_payload.get("provider_used"),
        model_used=answer_payload.get("model_used"),
        not_found=bool(answer_payload.get("not_found")),
        visible_steps=visible_steps,
        metadata=metadata,
    )
    message_count = len(history) + 2
    if payload.memory_enabled and session.memory_enabled and message_count % settings.memory_summary_interval == 0:
        emit("memory_refresh", "Memperbarui ringkasan memori aman", "running")
        refresh_session_memory(db, session.id)
        emit("memory_refresh", "Memperbarui ringkasan memori aman", "done")
    if settings.llm_title_generation_enabled:
        emit("title", "Meringkas judul chat", "running")
        title = maybe_refine_title_with_llm(db, session.id, payload.question, payload.provider_override)
        emit("title", "Meringkas judul chat", "done", title)
    emit("save_answer", "Menyimpan jawaban dan metadata", "done", f"Message {assistant.id}")
    assistant.visible_steps = visible_steps
    db.commit()
    return {
        "session_id": session.id,
        "message_id": assistant.id,
        "answer": answer_payload["answer"],
        "sources": answer_payload.get("sources") or [],
        "confidence": answer_payload.get("confidence"),
        "not_found": bool(answer_payload.get("not_found")),
        "provider_used": answer_payload.get("provider_used"),
        "model_used": answer_payload.get("model_used"),
        "memory_used": bool(memories),
        "chat_title": title,
        "visible_steps": visible_steps,
        "intent": intent_result.intent,
        "retrieval_mode": payload.retrieval_mode,
        "language_detected": language_detected,
        "retrieved_context_count": len(contexts),
        "prompt_context_chunk_count": min(len(contexts), top_k),
        "indexed_context_count": agent_result.indexed_context_count if agent_result else 0,
        "web_context_count": agent_result.web_context_count if agent_result else 0,
        "agent_tool_calls": agent_result.agent_tool_calls if agent_result else 0,
        "retrieval_fallback_used": agent_result.retrieval_fallback_used if agent_result else False,
        "retrieval_warnings": agent_result.retrieval_warnings if agent_result else [],
    }


@router.post("/chat")
def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    apply_chat_safeguards(request, question=payload.question, anonymous_session_id=payload.anonymous_session_id)
    return process_chat(payload, db)


def _sse(event: str, data) -> str:
    # default=str keeps datetime/UUID fields (e.g. source freshness) from breaking
    # the SSE stream with "Object of type datetime is not JSON serializable".
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest, request: Request):
    apply_chat_safeguards(request, question=payload.question, anonymous_session_id=payload.anonymous_session_id)

    def generator():
        queue: Queue[tuple[str, object]] = Queue()

        def worker():
            try:
                session_factory = get_session_local()
                with session_factory() as worker_db:
                    result = process_chat(payload, worker_db, emit_step=lambda step: queue.put(("step", step)))
                queue.put(("sources", result.get("sources", [])))
                queue.put(("final", result))
            except HTTPException as exc:
                queue.put(("error", {"detail": exc.detail}))
            except Exception as exc:
                queue.put(("error", {"detail": str(exc)}))
            finally:
                queue.put(("done", {}))

        Thread(target=worker, daemon=True).start()
        while True:
            event, data = queue.get()
            if event == "done":
                return
            yield _sse(event, data)

    return StreamingResponse(generator(), media_type="text/event-stream")
