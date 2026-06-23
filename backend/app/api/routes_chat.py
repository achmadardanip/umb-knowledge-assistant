from __future__ import annotations

import json
import re
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
from app.chat.session_service import (
    create_session,
    get_session,
    maybe_autotitle_session,
    maybe_contextualize_session_title,
    maybe_refine_title_with_llm,
)
from app.chat.clarify import clarification_suggestions, clarifying_questions
from app.chat.followups import suggest_followups
from app.chat.prepare_store import PreparedGeneration, prepare_store
from app.chat.role_inference import infer_audience
from app.chat.summarizer import compact_context
from app.core.config import get_settings
from app.db.database import get_db, get_session_local
from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider
from app.rag.answer_cache import build_cache_key, get_cached_answer, store_cached_answer
from app.rag.answer_generator import build_generation_messages, finalize_generated_answer, generate_answer
from app.rag.guardrails import guardrail_response
from app.rag.intent_classifier import classify_intent
from app.rag.language import detect_language
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.intent_gate import admin_contact_line, detect_retrieval_intent, history_conflicts, refusal_message
from app.web_search.tavily_client import WebSearchConfigurationError


router = APIRouter(tags=["chat"])


StepStatus = Literal["running", "done", "skipped", "error"]


class ChatRequest(BaseModel):
    session_id: str | None = None
    anonymous_session_id: str | None = None
    question: str = Field(min_length=1)
    top_k: int = 5
    provider_override: Literal[
        "local_ollama",
        "local_lmstudio",
        "openrouter",
        "openai",
        "gemini",
        "anthropic",
        "hermes",
        "groq",
        "huggingface",
    ] | None = None
    memory_enabled: bool = True
    regenerate_from_message_id: str | None = None
    retrieval_mode: RetrievalMode = "hybrid"
    audience: Literal["calon_mahasiswa", "mahasiswa", "orang_tua", "alumni", "dosen", "publik"] | None = None
    language: str | None = None
    include_retrieved_context: bool = False
    answer_model: str | None = None   # eval-only: override the local LLM (brain comparison)


def _ensure_session(db: Session, payload: ChatRequest):
    if payload.session_id:
        session = get_session(db, payload.session_id)
        if session:
            return session
        # The client sent a session id that doesn't exist here (e.g. a stale id
        # cached in the browser from a previous DB, or after a restore). Don't break
        # the chat with a 404 — transparently start a fresh session for this client.
    return create_session(db, payload.anonymous_session_id)


_AUDIENCE_HINT = {
    "calon_mahasiswa": "Pengguna adalah calon mahasiswa; utamakan info pendaftaran, biaya, program studi, dan jalur masuk.",
    "mahasiswa": "Pengguna adalah mahasiswa aktif; utamakan info akademik, SIA/SSO, jadwal kuliah, dan layanan kemahasiswaan.",
    "orang_tua": "Pengguna adalah orang tua/wali; gunakan bahasa yang mudah dan soroti biaya, jadwal, serta kontak resmi.",
    "alumni": "Pengguna adalah alumni; utamakan info ijazah, legalisir, tracer study, dan layanan alumni.",
    "dosen": "Pengguna adalah dosen/staf; utamakan info kepegawaian, sistem akademik, dan layanan internal yang bersifat publik.",
    "publik": "Pengguna adalah masyarakat umum.",
}


def _with_audience(question: str, audience: str | None) -> str:
    hint = _AUDIENCE_HINT.get(audience or "")
    return f"[Konteks pengguna] {hint}\n\nPertanyaan: {question}" if hint else question


def _retrieved_context_payload(contexts: list[dict], include: bool) -> dict:
    """Eval-only: expose retrieved chunk texts so Promptfoo can grade faithfulness."""
    if not include:
        return {}
    chunks = [(c.get("chunk_text") or "") for c in contexts]
    return {
        "retrieved_context": chunks,
        "retrieved_context_joined": "\n\n".join(chunks)[:8000],
    }


_FASILKOM_MARKERS = ("fasilkom", "fakultas ilmu komputer")
_FACULTY_REFERENCE_TERMS = ("fakultas ini", "fakultas tersebut", "di fakultas ini", "prodi ini", "program studi ini")
_FACULTY_PROGRAM_TERMS = ("program studi", "prodi", "jurusan", "program")
_FACULTY_ROLE_TERMS = ("dekan", "wakil dekan", "dosen", "struktural", "ketua program studi", "kaprodi")


def _lower_blob(*parts) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _history_blob(history: list[dict], chat_title: str | None = None) -> str:
    fragments = [chat_title or ""]
    for message in history or []:
        fragments.append(message.get("content") or "")
        for source in (message.get("sources") or [])[:3]:
            if not isinstance(source, dict):
                continue
            fragments.extend([source.get("title") or "", source.get("hostname") or "", source.get("url") or ""])
    return _lower_blob(*fragments)


def _mentions_fasilkom(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _FASILKOM_MARKERS)


def _needs_faculty_context(question: str) -> bool:
    lowered = (question or "").lower()
    return any(term in lowered for term in _FACULTY_REFERENCE_TERMS)


def _contextual_query_hints(question: str, history: list[dict], chat_title: str | None = None) -> list[str]:
    question_lc = (question or "").lower()
    context_lc = _history_blob(history, chat_title)
    has_fasilkom_context = _mentions_fasilkom(question_lc) or (_needs_faculty_context(question_lc) and _mentions_fasilkom(context_lc))
    if not has_fasilkom_context:
        return []

    hints = ["Konteks entitas: Fakultas Ilmu Komputer (Fasilkom) Universitas Mercu Buana."]
    if any(term in question_lc for term in _FACULTY_REFERENCE_TERMS):
        hints.append("Maksud frasa seperti 'fakultas ini' adalah Fakultas Ilmu Komputer/Fasilkom.")
    if any(term in question_lc for term in _FACULTY_ROLE_TERMS):
        hints.append("Prioritaskan halaman struktural dan dosen Fasilkom/Fakultas Ilmu Komputer.")
    if any(term in question_lc for term in _FACULTY_PROGRAM_TERMS):
        hints.append("Cari program studi/prodi Fakultas Ilmu Komputer/Fasilkom, bukan berita, event, repository, atau perpustakaan.")
    return hints


def _context_matches_fasilkom(context: dict) -> bool:
    combined = _lower_blob(
        context.get("title"),
        context.get("hostname"),
        context.get("url"),
        context.get("chunk_text"),
    )
    return _mentions_fasilkom(combined)


def _filter_contexts_for_question(query: str, contexts: list[dict]) -> tuple[list[dict], str | None]:
    if not contexts or not _mentions_fasilkom(query):
        return contexts, None
    focused = [context for context in contexts if _context_matches_fasilkom(context)]
    if focused:
        return focused, f"{len(contexts) - len(focused)} konteks non-Fasilkom disaring"
    return [], "Tidak ada konteks yang cocok dengan Fakultas Ilmu Komputer/Fasilkom"


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


# Canonical faculty / program phrases for the sticky-entity carry (Phase 19 P19.2).
# Ordered longest-first per faculty so the full name wins over the bare acronym.
_STICKY_FACULTY = [
    ("fakultas ekonomi dan bisnis", "Fakultas Ekonomi dan Bisnis"),
    ("fakultas ilmu komputer", "Fakultas Ilmu Komputer"),
    ("fakultas ilmu komunikasi", "Fakultas Ilmu Komunikasi"),
    ("fakultas desain dan seni kreatif", "Fakultas Desain dan Seni Kreatif"),
    ("fakultas psikologi", "Fakultas Psikologi"),
    ("fakultas teknik", "Fakultas Teknik"),
    ("pascasarjana", "Pascasarjana"),
    ("fasilkom", "Fakultas Ilmu Komputer"),
    ("fikom", "Fakultas Ilmu Komunikasi"),
    ("fdsk", "Fakultas Desain dan Seni Kreatif"),
    ("fpsi", "Fakultas Psikologi"),
    ("feb", "Fakultas Ekonomi dan Bisnis"),
]
def _sticky_entity_hint(prior_messages: list[dict]) -> str | None:
    """Most recent explicitly-named FACULTY in the user's prior turns (scans the
    full history, newest first). Faculties only — program names are ambiguous
    ("psikologi"/"manajemen" are both faculty and program tokens) and over-match,
    so carrying them hurt resolution. Returns the canonical faculty name or None."""
    user_turns = [m.get("content", "") or "" for m in prior_messages if m.get("role") == "user"]
    for text_turn in reversed(user_turns):
        low = text_turn.lower()
        for needle, canonical in _STICKY_FACULTY:
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", low):
                return canonical
    return None


def _build_retrieval_query(question: str, history: list[dict], chat_title: str | None = None, *, is_followup: bool = True, intent: str | None = None) -> str:
    # NEW_TOPIC: retrieve on the question alone. Carrying prior turns / source
    # hints / entity hints would leak the previous topic's context into an
    # unrelated question (e.g. SIA login after a FASILKOM-dean question). Only a
    # genuine follow-up inherits conversation context.
    if not is_followup:
        return compact_context([question], max_chars=1600)

    prior_messages = list(history or [])
    # Conversation context must never override the current query's intent: a chat
    # titled "Informasi Fasilkom UMB" must not steer a SIA-login question into
    # faculty pages. Drop conflicting title/turns before building the query.
    if intent:
        if chat_title and chat_title != "New Chat" and history_conflicts(intent, chat_title):
            chat_title = None
        prior_messages = [
            message
            for message in prior_messages
            if not history_conflicts(intent, message.get("content") or "")
        ]
    normalized_question = " ".join((question or "").split()).lower()
    for index in range(len(prior_messages) - 1, -1, -1):
        message = prior_messages[index]
        if message.get("role") == "user" and " ".join((message.get("content") or "").split()).lower() == normalized_question:
            prior_messages.pop(index)
            break

    # Sticky entity (Phase 19 P19.2): on a long follow-up chain the establishing
    # faculty scrolls out of the recent-turns window, leaving an elliptical query
    # ("siapa dekannya?") with no entity to resolve. Carry the most recent
    # explicitly-named faculty from the FULL history (faculties only — programs are
    # ambiguous and over-match) so deep PRIMARY follow-ups keep their subject.
    # Follow-up path only — single-shot retrieval (the 0.998 benchmark) is unaffected.
    sticky = _sticky_entity_hint(prior_messages)
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

    parts = [question, *_contextual_query_hints(question, prior_messages, chat_title)]
    if sticky and sticky.lower() not in question.lower():
        parts.append(f"Konteks entitas: {sticky}")
    if chat_title and chat_title != "New Chat":
        parts.append(f"Judul chat: {chat_title}")
    if recent_user_turns:
        parts.extend(["Konteks pertanyaan sebelumnya:", *recent_user_turns])
    if source_hints:
        parts.extend(["Sumber resmi yang pernah relevan:", *source_hints[:5]])
    return compact_context(parts, max_chars=1600)


def _apply_answer_policy(answer_payload: dict, intent: str, language: str | None) -> str | None:
    """Final answer policy (spec #7/#8/#10/#13).

    A verified answer is left untouched (its validated citations stay). But an
    *unverified* result — ``not_found`` or the extractive "could not verify" fallback —
    must never masquerade as an answer backed by candidate source cards. For sensitive
    intents that have a refusal template (login/SSO, support, faculty) we replace the
    text with a safe refusal and drop all source cards. Returns a refusal reason or None.
    """
    is_extractive = (answer_payload.get("metadata") or {}).get("fallback") == "extractive"
    unverified = bool(answer_payload.get("not_found")) or is_extractive
    if not unverified:
        return None
    # Never show candidate source cards on a non-answer.
    answer_payload["sources"] = []
    answer_payload["confidence"] = "low"
    answer_payload["not_found"] = True
    answer_payload["provider_used"] = "system"
    # Sensitive intents get a tailored refusal; everything else gets the clean
    # "no verified answer -> contact the WhatsApp admin" fallback. Either way: no guessing.
    refusal = refusal_message(intent, language)
    if refusal:
        answer_payload["answer"] = refusal
        answer_payload["model_used"] = "intent-refusal"
        answer_payload["metadata"] = {**(answer_payload.get("metadata") or {}), "intent_refusal": True}
        return f"unverified_context_for_intent:{intent}"
    answer_payload["answer"] = _fallback_answer_for_language(language)
    answer_payload["model_used"] = "fallback"
    answer_payload["metadata"] = {**(answer_payload.get("metadata") or {}), "fallback": "no_verified_answer"}
    return "no_verified_answer"


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


def _fallback_answer_for_language(language: str | None, query: str | None = None) -> str:
    if _mentions_fasilkom(query or ""):
        if (language or "").lower().startswith("en"):
            return (
                "I have not found sufficiently relevant official sources about the Faculty of Computer Science/Fasilkom "
                "in the current index. Please index the faculty, structure, or study-program pages first."
            )
        return (
            "Saya belum menemukan sumber resmi yang cukup relevan tentang Fakultas Ilmu Komputer/Fasilkom dari indeks saat ini. "
            "Coba indeks halaman fakultas, struktural, atau program studi UMB terlebih dahulu."
        )
    if (language or "").lower().startswith("en"):
        body = "I could not find verified official Universitas Mercu Buana information for that question, so I will not guess."
    else:
        body = "Saya belum menemukan informasi resmi yang terverifikasi terkait pertanyaan tersebut pada sumber publik Universitas Mercu Buana, jadi saya tidak menebak."
    return f"{body}\n\n{admin_contact_line(language)}"


def process_chat(payload: ChatRequest, db: Session, emit_step=None, defer_generation: bool = False) -> dict:
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
    title = maybe_contextualize_session_title(db, session.id, payload.question, history)
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
        {"intent": intent_result.intent, "topic": intent_result.topic, "confidence": intent_result.confidence},
    )

    if intent_result.intent in {"smalltalk", "capability_query"}:
        if intent_result.intent == "capability_query":
            answer_text = (
                "I can help search official public UMB information from indexed or live official sources, such as faculties, study programs, lecturers or faculty structure, admissions, fees, scholarships, SSO/SIA, library services, campus activities, and other official pages. For academic or administrative decisions, please verify with the relevant UMB unit."
                if language_detected.startswith("en")
                else "Saya bisa membantu mencari informasi publik resmi UMB dari sumber resmi yang sudah diindeks atau mode live, seperti fakultas, program studi, dosen/struktur fakultas, pendaftaran, biaya, beasiswa, SSO/SIA, perpustakaan, kegiatan kampus, dan halaman resmi lain. Untuk keputusan akademik atau administratif, tetap verifikasi ke unit resmi UMB."
            )
        else:
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
        emit("answer", "Menjawab tanpa provider AI", "done", f"Tidak memakai RAG/LLM karena intent {intent_result.intent}")
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

    # Ask clarifying questions for vague/ambiguous queries *before* spending retrieval
    # or the rate-limited LLM. Skipped for out-of-scope and for regenerate requests.
    clarifiers: list[str] = []
    if intent_result.intent != "out_of_scope" and not payload.regenerate_from_message_id:
        clarifiers = clarifying_questions(payload.question, recent_messages=history, language=language_detected)
        if clarifiers:
            # Don't ask to clarify a question the canonical FAQ already answers
            # completely (e.g. "Beasiswa apa saja?"). A strong FAQ match means we
            # have a grounded, complete answer — answer it instead of stalling.
            from app.retrieval.faq_retriever import match_faq

            faq_hits = match_faq(db, payload.question)
            if any(not h.get("intent_demoted") and float(h.get("score") or 0.0) >= 12.0 for h in faq_hits):
                clarifiers = []
                emit("clarify", "Melewati klarifikasi", "skipped", "FAQ kanonik resmi sudah menjawab; lanjut ke retrieval")
    if clarifiers:
        is_en = language_detected.startswith("en")
        emit("clarify", "Meminta klarifikasi konteks", "done",
             "Pertanyaan terlalu umum/ambigu; menanyakan detail tanpa memanggil LLM")
        suggestions = clarification_suggestions(payload.question, recent_messages=history, language=language_detected)
        lead = (
            "Your question is still quite general. So I can answer accurately from official UMB sources, could you clarify:"
            if is_en
            else "Pertanyaan Anda masih cukup umum. Agar saya bisa menjawab dengan tepat dari sumber resmi UMB, boleh perjelas dulu:"
        )
        answer_text = lead + "\n\n" + "\n".join(f"• {q}" for q in clarifiers)
        clarify_meta = {
            "memory_used": False,
            "intent": intent_result.intent,
            "retrieval_mode": payload.retrieval_mode,
            "language_detected": language_detected,
            "retrieved_context_count": 0,
            "prompt_context_chunk_count": 0,
            "indexed_context_count": 0,
            "web_context_count": 0,
            "agent_tool_calls": 0,
            "clarification": True,
        }
        emit("save_answer", "Menyimpan jawaban dan metadata", "running")
        assistant = save_message(
            db,
            session_id=session.id,
            role="assistant",
            content=answer_text,
            sources=[],
            confidence_score="low",
            provider_used="system",
            model_used="clarification",
            not_found=False,
            visible_steps=visible_steps,
            metadata=clarify_meta,
        )
        emit("save_answer", "Menyimpan jawaban dan metadata", "done", f"Message {assistant.id}")
        assistant.visible_steps = visible_steps
        db.commit()
        return {
            "session_id": session.id,
            "message_id": assistant.id,
            "answer": answer_text,
            "sources": [],
            "confidence": "low",
            "not_found": False,
            "provider_used": "system",
            "model_used": "clarification",
            "memory_used": False,
            "cache_hit": False,
            "follow_up_questions": suggestions,
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

    from app.rag.intent_router import analyze_followup

    # P3 conversation-state isolation: a confidence-scored decision. Below the
    # threshold (or on an intent/topic switch) we START A NEW CONTEXT — neither the
    # retrieval query NOR the generation prompt inherits the prior turn's
    # entity/topic context (the SIA-after-FASILKOM leakage). ``conversation_history``
    # is the per-turn-scoped memory handed to generation; it is emptied on a new topic.
    followup = analyze_followup(payload.question, history)
    is_followup = followup.is_followup
    conversation_history = history if is_followup else []
    emit(
        "followup_detection",
        "Mendeteksi pertanyaan lanjutan vs topik baru",
        "done",
        (
            f"Pertanyaan lanjutan (conf {followup.confidence:.2f}): mewarisi konteks percakapan"
            if is_followup
            else f"Topik baru (conf {followup.confidence:.2f}, {followup.reason}): konteks percakapan direset"
        ),
        {
            "is_followup": is_followup,
            "followup_confidence": followup.confidence,
            "intent_changed": followup.intent_changed,
            "topic_changed": followup.topic_changed,
            "reason": followup.reason,
            "prev_intent": followup.prev_intent,
            "cur_intent": followup.cur_intent,
        },
    )
    # Retrieval intent (login/SSO, support, faculty, tuition, …) drives the hard
    # intent gate in the agent and the conversation-context conflict drop. It is
    # distinct from intent_result.intent (smalltalk/capability/out_of_scope/general).
    # Phase 27.3 — normalize informal/typo'd queries ("brp biaya kuliah ti",
    # "akreditsi sistem informasi") before retrieval. Idempotent on clean text;
    # applied only to the live chat query (benchmarks call the retriever directly).
    from app.rag.query_normalizer import normalize_query

    retrieval_question = normalize_query(payload.question)
    retrieval_intent = detect_retrieval_intent(retrieval_question)
    retrieval_query = _build_retrieval_query(
        retrieval_question, history, title, is_followup=is_followup, intent=retrieval_intent
    )
    if intent_result.topic != "general":
        retrieval_query = f"{retrieval_query}\nTopik terdeteksi: {intent_result.topic}"

    # Phase 20 P20.1/P20.2 — session entity memory: resolve elliptical follow-ups
    # ("beliau menjabat sejak kapan?", "akreditasinya bagaimana?") against the
    # subject established earlier in THIS session. Only enriches a genuine elliptical
    # follow-up; never overrides a self-contained question. Per-session + auto-
    # expiring, so the (session-less) retrieval benchmark is unaffected.
    from app.chat.memory_provider import get_memory_provider
    from app.rag.followup_resolution import resolve_followup

    # Phase 24: pluggable memory backend (in-process or Postgres for multi-worker).
    _session_memory = get_memory_provider()
    _session_ctx = _session_memory.recall(session.id, db)
    if is_followup and _session_ctx is not None:
        _resolved = resolve_followup(payload.question, _session_ctx)
        if _resolved.enrichment_hint and _resolved.resolved_reference and \
                _resolved.resolved_reference.lower() not in retrieval_query.lower():
            retrieval_query = f"{retrieval_query}\n{_resolved.enrichment_hint}"
            emit("session_memory", "Memori entitas sesi", "done",
                 f"Referensi lanjutan diselesaikan: {_resolved.resolved_reference}",
                 {"resolved_reference": _resolved.resolved_reference})

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
                match_query=payload.question,
                intent=retrieval_intent,
            )
        except WebSearchConfigurationError as exc:
            db.rollback()
            emit("umb_live_web_search", "Mencari sumber live resmi UMB", "error", str(exc))
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        contexts = agent_result.contexts
        filtered_contexts, filter_detail = _filter_contexts_for_question(retrieval_query, contexts)
        if filter_detail:
            emit(
                "context_filter",
                "Memfilter konteks sesuai entitas percakapan",
                "done" if filtered_contexts else "skipped",
                filter_detail,
                {"before": len(contexts), "after": len(filtered_contexts), "entity": "fasilkom"},
            )
            contexts = filtered_contexts
    summary_detail, summary_metadata = _context_summary(contexts)
    emit("retrieval", "Mencari sumber resmi UMB", "done" if contexts else "skipped", summary_detail, summary_metadata)

    # Phase 20 P20.1 — update session entity memory from this turn's resolved
    # entities so the NEXT elliptical follow-up can be resolved.
    try:
        _session_memory.remember(session.id, query=payload.question, contexts=contexts, intent=retrieval_intent, db=db)
    except Exception:
        pass

    emit("provider", "Memilih provider AI", "running")
    provider_used, model_used = _provider_meta(payload.provider_override)
    emit("provider", "Memilih provider AI", "done", f"{provider_used} / {model_used}")

    if not contexts:
        emit("answer", "Menyusun jawaban fallback", "done", "Tidak ada konteks resmi yang cukup")
        answer_payload = {
            "answer": _fallback_answer_for_language(language_detected, retrieval_query),
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
                if defer_generation:
                    messages, prepared_contexts = build_generation_messages(
                        question=_with_audience(payload.question, payload.audience or infer_audience(payload.question)),
                        contexts=contexts,
                        recent_messages=conversation_history,
                        memories=memories,
                        language=language_detected,
                    )
                    if settings.web_kb_ingest_enabled:
                        web_used = [c for c in contexts if c.get("discovery_source") == "live_web_search"]
                        if web_used:
                            from app.ingestion.async_acquisition import schedule_kb_acquisition

                            schedule_kb_acquisition(payload.question, web_used)
                    prepared = PreparedGeneration(
                        session_id=session.id,
                        raw_question=payload.question,
                        contexts=prepared_contexts,
                        language=language_detected,
                        intent=intent_result.intent,
                        retrieval_mode=payload.retrieval_mode,
                        memory_used=bool(memories),
                        top_k=top_k,
                        indexed_context_count=agent_result.indexed_context_count if agent_result else 0,
                        web_context_count=agent_result.web_context_count if agent_result else 0,
                        agent_tool_calls=agent_result.agent_tool_calls if agent_result else 0,
                        visible_steps=visible_steps,
                    )
                    prepare_id = prepare_store.put(prepared)
                    emit("prepare", "Menyiapkan prompt untuk LLM di browser (Puter.js)", "done",
                         f"{len(prepared_contexts)} konteks resmi disertakan; generasi tanpa API key di browser")
                    db.commit()
                    return {
                        "mode": "generate",
                        "prepare_id": prepare_id,
                        "messages": messages,
                        "session_id": session.id,
                        "chat_title": title,
                        "language_detected": language_detected,
                        "intent": intent_result.intent,
                        "retrieval_mode": payload.retrieval_mode,
                        "visible_steps": visible_steps,
                        "retrieved_context_count": len(contexts),
                        "prompt_context_chunk_count": min(len(contexts), top_k),
                        "indexed_context_count": prepared.indexed_context_count,
                        "web_context_count": prepared.web_context_count,
                        "agent_tool_calls": prepared.agent_tool_calls,
                    }
                emit("answer", "Menyusun jawaban berbasis sumber resmi", "running", f"Mengirim {len(contexts)} chunk relevan, bukan seluruh dokumen")
                answer_payload = generate_answer(
                    question=_with_audience(payload.question, payload.audience or infer_audience(payload.question)),
                    contexts=contexts,
                    recent_messages=conversation_history,
                    memories=memories,
                    provider_override=payload.provider_override,
                    language=language_detected,
                    answer_model=payload.answer_model,
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

    # Final answer policy: an unverified result (not_found, or — if ever re-enabled —
    # an extractive "could not verify" fallback) must never masquerade as an answer
    # backed by candidate source cards. Sensitive intents get a tailored refusal;
    # everything else gets the clean "no verified answer -> WhatsApp admin" fallback.
    policy_reason = _apply_answer_policy(answer_payload, retrieval_intent, language_detected)
    if policy_reason:
        emit(
            "answer_policy",
            "Menerapkan kebijakan jawaban terverifikasi",
            "done",
            "Jawaban tak terverifikasi diganti dengan fallback aman; kartu sumber dikosongkan",
            {"refusal_reason": policy_reason, "intent": retrieval_intent},
        )

    # Async knowledge acquisition (Batch 4): the user is answered FIRST; persisting
    # the live-web sources into the KB + recording the discovery cache runs in a
    # background thread (its own DB session), so a similar future question is served
    # from the indexed KB without another billed Tavily round-trip.
    web_kb_ingested = 0
    if settings.web_kb_ingest_enabled and not answer_payload.get("not_found") and not answer_payload.get("cache_hit"):
        web_used = [c for c in contexts if c.get("discovery_source") == "live_web_search"]
        if web_used:
            from app.ingestion.async_acquisition import schedule_kb_acquisition

            scheduled = schedule_kb_acquisition(payload.question, web_used)
            emit("kb_ingest", "Menjadwalkan akuisisi pengetahuan", "done" if scheduled else "skipped",
                 f"{len(web_used)} sumber web dijadwalkan untuk diindeks di latar belakang" if scheduled else "Tidak ada sumber web untuk diindeks")

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
    # Phase 16 P16.2 — enrich the returned sources with freshness metadata
    # (additive; does not affect ranking or which sources were chosen).
    from app.rag.freshness import enrich_sources_with_freshness

    enriched_sources = enrich_sources_with_freshness(db, answer_payload.get("sources") or [])
    return {
        "session_id": session.id,
        "message_id": assistant.id,
        "answer": answer_payload["answer"],
        "sources": enriched_sources,
        "confidence": answer_payload.get("confidence"),
        "not_found": bool(answer_payload.get("not_found")),
        "provider_used": answer_payload.get("provider_used"),
        "model_used": answer_payload.get("model_used"),
        "memory_used": bool(memories),
        "cache_hit": bool(answer_payload.get("cache_hit")),
        "follow_up_questions": suggest_followups(payload.question, language_detected),
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
        **_retrieved_context_payload(contexts, payload.include_retrieved_context),
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


class ChatFinalizeRequest(BaseModel):
    prepare_id: str
    answer: str = Field(min_length=1)
    model_used: str | None = None


@router.post("/chat/prepare")
def chat_prepare(payload: ChatRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Run the full RAG pipeline up to (not incl.) generation for the browser LLM path.

    Returns either a terminal answer (mode='final': smalltalk/blocked/clarify/cache/
    not_found — no LLM needed) or mode='generate' with the grounded prompt messages
    and a prepare_id the browser uses after calling puter.ai.chat(...).
    """
    apply_chat_safeguards(request, question=payload.question, anonymous_session_id=payload.anonymous_session_id)
    result = process_chat(payload, db, defer_generation=True)
    if result.get("mode") == "generate":
        return result
    return {**result, "mode": "final"}


@router.post("/chat/finalize")
def chat_finalize(payload: ChatFinalizeRequest, db: Session = Depends(get_db)) -> dict:
    """Verify + persist a browser-generated (Puter.js) answer against server-vetted
    contexts. The same trust gate as server providers: citation validation + CGCV +
    output safety, so the keyless browser path is not a verification bypass."""
    prepared = prepare_store.pop(payload.prepare_id)
    if prepared is None:
        raise HTTPException(status_code=410, detail="Sesi generasi kedaluwarsa. Silakan kirim ulang pertanyaan.")

    settings = get_settings()
    model_used = payload.model_used or "puter-browser"
    answer_payload = finalize_generated_answer(
        payload.answer,
        prepared.contexts,
        provider_used="puter",
        model_used=model_used,
        memory_used=prepared.memory_used,
        language=prepared.language,
    )
    # Same intent answer policy as the server path: an unverified/extractive browser
    # answer for a sensitive intent becomes a safe refusal with no candidate cards.
    finalize_refusal_reason = _apply_answer_policy(
        answer_payload, detect_retrieval_intent(prepared.raw_question), prepared.language
    )
    final_model = answer_payload.get("model_used") or model_used

    if settings.rag_answer_cache_enabled and not answer_payload.get("not_found") and (answer_payload.get("metadata") or {}).get("fallback") != "extractive":
        try:
            cache_key = build_cache_key(
                question=prepared.raw_question,
                intent=prepared.intent,
                provider_used="puter",
                model_used=final_model,
                contexts=prepared.contexts,
                memory_enabled=prepared.memory_used,
            )
            store_cached_answer(
                db,
                cache_key=cache_key,
                question=prepared.raw_question,
                intent=prepared.intent,
                provider_used="puter",
                model_used=final_model,
                answer_payload=answer_payload,
                ttl_seconds=settings.rag_answer_cache_ttl_seconds,
            )
        except Exception:  # caching is best-effort
            db.rollback()

    metadata = {
        "memory_used": prepared.memory_used,
        "intent": prepared.intent,
        "retrieval_mode": prepared.retrieval_mode,
        "language_detected": prepared.language,
        "retrieved_context_count": len(prepared.contexts),
        "prompt_context_chunk_count": min(len(prepared.contexts), prepared.top_k),
        "indexed_context_count": prepared.indexed_context_count,
        "web_context_count": prepared.web_context_count,
        "agent_tool_calls": prepared.agent_tool_calls,
        "cache_hit": False,
        "retrieval_debug": {
            "detected_intent": detect_retrieval_intent(prepared.raw_question),
            "final_citations": len(answer_payload.get("sources") or []),
            "refusal_reason": finalize_refusal_reason,
        },
    }
    assistant = save_message(
        db,
        session_id=prepared.session_id,
        role="assistant",
        content=answer_payload["answer"],
        sources=answer_payload.get("sources") or [],
        confidence_score=answer_payload.get("confidence"),
        provider_used="puter",
        model_used=final_model,
        not_found=bool(answer_payload.get("not_found")),
        visible_steps=prepared.visible_steps,
        metadata=metadata,
    )
    assistant.visible_steps = prepared.visible_steps
    # Keep session memory current on the browser-LLM path too (rule-based, self-gates
    # on session.memory_enabled). Without this, Puter conversations never summarise.
    try:
        refresh_session_memory(db, prepared.session_id)
    except Exception:  # memory is best-effort; never break the answer
        pass
    db.commit()
    return {
        "session_id": prepared.session_id,
        "message_id": assistant.id,
        "answer": answer_payload["answer"],
        "sources": answer_payload.get("sources") or [],
        "confidence": answer_payload.get("confidence"),
        "not_found": bool(answer_payload.get("not_found")),
        "provider_used": "puter",
        "model_used": final_model,
        "memory_used": prepared.memory_used,
        "cache_hit": False,
        "follow_up_questions": suggest_followups(prepared.raw_question, prepared.language),
        "visible_steps": prepared.visible_steps,
        "intent": prepared.intent,
        "retrieval_mode": prepared.retrieval_mode,
        "language_detected": prepared.language,
        "retrieved_context_count": len(prepared.contexts),
        "prompt_context_chunk_count": min(len(prepared.contexts), prepared.top_k),
        "indexed_context_count": prepared.indexed_context_count,
        "web_context_count": prepared.web_context_count,
        "agent_tool_calls": prepared.agent_tool_calls,
    }
