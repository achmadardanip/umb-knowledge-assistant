from __future__ import annotations

import json
import logging
import re
import time

from app.core.config import get_settings
from app.core.output_filter import sanitize_answer
from app.llm.base import ProviderConfigurationError
from app.llm.provider_factory import get_provider, normalize_provider
from app.rag.citation_validator import FALLBACK_ANSWER, validate_citations
from app.rag.language import language_instruction
from app.rag.prompts import SYSTEM_PROMPT, build_context_block
from app.verification.claim_gate import verify_claims
from app.verification.entailment import EntailmentChecker, LexicalEntailmentChecker, LLMJudgeEntailmentChecker


logger = logging.getLogger(__name__)


def fallback_payload(memory_used: bool = False, provider_used: str | None = None, model_used: str | None = None) -> dict:
    return {
        "answer": FALLBACK_ANSWER,
        "sources": [],
        "confidence": "low",
        "not_found": True,
        "provider_used": provider_used,
        "model_used": model_used,
        "memory_used": memory_used,
    }


def _build_sources(contexts: list[dict]) -> list[dict]:
    sources = []
    for index, context in enumerate(contexts, start=1):
        sources.append(
            {
                "citation_id": index,
                "title": context.get("title") or context.get("url"),
                "url": context.get("url"),
                "hostname": context.get("hostname"),
                "source_type": context.get("source_type"),
                "relevance_score": round(float(context.get("score", 0.0)), 4),
                "page_number": context.get("page_number"),
                "slide_number": context.get("slide_number"),
                "sheet_name": context.get("sheet_name"),
                "row_range": context.get("row_range"),
                "timestamp_start": context.get("timestamp_start"),
                "timestamp_end": context.get("timestamp_end"),
                "extraction_method": context.get("extraction_method"),
                "extraction_confidence": context.get("extraction_confidence"),
                "discovery_source": context.get("discovery_source"),
                "last_verified": context.get("last_verified"),
                "authority": context.get("authority"),
            }
        )
    return sources


def _context_source_key(context: dict) -> tuple:
    return (
        context.get("url"),
        context.get("page_number"),
        context.get("slide_number"),
        context.get("sheet_name"),
        context.get("row_range"),
        context.get("timestamp_start"),
        context.get("timestamp_end"),
    )


def _unique_contexts_by_source(contexts: list[dict]) -> list[dict]:
    seen = set()
    unique_contexts: list[dict] = []
    for context in contexts:
        key = _context_source_key(context)
        if key in seen:
            continue
        seen.add(key)
        unique_contexts.append(context)
    return unique_contexts


def extractive_fallback_payload(
    *,
    contexts: list[dict],
    memory_used: bool = False,
    provider_used: str | None = None,
    model_used: str | None = None,
    reason: str | None = None,
) -> dict:
    fallback_contexts = _unique_contexts_by_source(contexts)[:5]
    sources = _build_sources(fallback_contexts)
    snippets = []
    for index, context in enumerate(fallback_contexts[:3], start=1):
        text = " ".join((context.get("chunk_text") or "").split())
        if not text:
            continue
        title = context.get("title") or context.get("hostname") or "Sumber resmi"
        snippets.append(f"**{title}** — {text[:240].rstrip()}… [{index}]")
    answer = FALLBACK_ANSWER
    if snippets:
        if reason and "missing_valid_citations" in reason:
            lead = (
                "Saya belum dapat memverifikasi jawaban yang utuh untuk pertanyaan ini dari sumber resmi yang terindeks, "
                "jadi saya tidak menebak. Berikut kutipan paling relevan dari sumber resmi UMB:"
            )
        else:
            lead = (
                "Sumber resmi yang relevan ditemukan, namun jawaban lengkap belum dapat disusun saat ini. "
                "Berikut kutipan paling relevan dari sumber resmi UMB:"
            )
        answer = lead + "\n\n" + "\n\n".join(f"- {snippet}" for snippet in snippets)
    payload = {
        "answer": answer,
        "sources": sources,
        "confidence": "medium" if sources else "low",
        "not_found": not bool(sources),
        "provider_used": provider_used,
        "model_used": model_used,
        "memory_used": memory_used,
        "metadata": {"fallback": "extractive", "reason": reason},
    }
    sanitized = validate_citations(payload, contexts, require_citation_markers=bool(sources))
    sanitized["answer"] = sanitize_answer(sanitized.get("answer") or "")
    return sanitized


def _is_retryable_provider_error(exc: Exception) -> bool:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in {408, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in ("429", "408", "500", "502", "503", "504", "timeout", "timed out"))


def _json_text(content: str) -> str:
    text = (content or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{"):
        return text
    # Browser models sometimes wrap the JSON in prose; extract the outermost object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _provider_candidates(provider_override: str | None) -> list[str | None]:
    settings = get_settings()
    selected = normalize_provider(provider_override)
    candidates: list[str | None] = [selected]
    for raw_provider in settings.llm_fallback_providers.split(","):
        provider_name = raw_provider.strip().lower()
        if not provider_name:
            continue
        normalized = normalize_provider(provider_name)
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates


def _chat_with_failover(messages: list[dict], provider_override: str | None, max_retries: int):
    settings = get_settings()
    last_error: Exception | None = None
    selected_provider = normalize_provider(provider_override)
    for candidate in _provider_candidates(provider_override):
        provider = get_provider(candidate)
        for attempt in range(max_retries + 1):
            try:
                return provider, provider.chat(messages), None
            except ProviderConfigurationError as exc:
                if provider.provider_name == selected_provider:
                    raise
                last_error = exc
                logger.warning("Fallback provider %s is not configured; skipping.", provider.provider_name)
                break
            except Exception as exc:
                last_error = exc
                retryable = _is_retryable_provider_error(exc)
                logger.warning(
                    "Provider %s call failed on attempt %s/%s: %s",
                    provider.provider_name,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                )
                if attempt >= max_retries or not retryable:
                    break
                time.sleep(settings.llm_retry_backoff_seconds * (2**attempt))
        if provider.provider_name != selected_provider and last_error:
            logger.warning("Fallback provider %s failed; trying next fallback if available.", provider.provider_name)
    return None, None, last_error


def _cgcv_enabled() -> bool:
    return get_settings().cgcv_enabled


def build_default_entailment_checker(provider_override: str | None) -> EntailmentChecker:
    """Entailment engine for CGCV. Default 'lexical' is free (no LLM call) so the trust
    gate runs on every answer without burning rate-limited quota; 'llm' uses a provider
    judge. Swappable for MiniCheck/NLI via the model gateway later."""
    settings = get_settings()
    if settings.cgcv_entailment_mode == "lexical":
        return LexicalEntailmentChecker()

    def chat(messages: list[dict]) -> str:
        return get_provider(provider_override).chat(messages).content

    return LLMJudgeEntailmentChecker(chat=chat)


def _contexts_by_citation(sources: list[dict], contexts: list[dict]) -> dict[int, dict]:
    contexts_by_url = {context.get("url"): context for context in contexts if context.get("url")}
    mapping: dict[int, dict] = {}
    for source in sources:
        citation_id = source.get("citation_id")
        url = source.get("url")
        if citation_id is None or not url:
            continue
        context = contexts_by_url.get(url)
        if context and context.get("chunk_text"):
            mapping[int(citation_id)] = context
    return mapping


_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def _min_confidence(first: str | None, second: str | None) -> str:
    first = first or "medium"
    second = second or "medium"
    return first if _CONFIDENCE_ORDER.get(first, 1) <= _CONFIDENCE_ORDER.get(second, 1) else second


def _apply_cgcv(payload: dict, contexts: list[dict], provider_override: str | None) -> dict:
    """Verify each cited claim by entailment; drop unsupported claims, abstain if too few survive."""
    settings = get_settings()
    sources = payload.get("sources") or []
    checker = build_default_entailment_checker(provider_override)
    result = verify_claims(
        payload.get("answer") or "",
        _contexts_by_citation(sources, contexts),
        checker,
        threshold=settings.cgcv_entailment_threshold,
        min_supported=settings.cgcv_min_supported_claims,
    )
    if result.not_found:
        return {**payload, "answer": FALLBACK_ANSWER, "sources": [], "confidence": "low", "not_found": True}
    surviving_ids = {citation_id for claim in result.supported_claims for citation_id in claim.citation_ids}
    filtered_sources = [source for source in sources if int(source.get("citation_id") or 0) in surviving_ids] or sources
    return {
        **payload,
        "answer": result.answer,
        "sources": filtered_sources,
        "confidence": _min_confidence(payload.get("confidence"), result.confidence),
        "not_found": False,
    }


def build_generation_messages(
    *,
    question: str,
    contexts: list[dict],
    recent_messages: list[dict] | None = None,
    memories: list[dict] | None = None,
    language: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build the grounded LLM prompt. Returns (messages, truncated_contexts).

    Shared by the server-side providers and the browser (Puter.js) path so both
    answer from the *same* official-context-only prompt.
    """
    settings = get_settings()
    contexts = contexts[: max(1, settings.rag_top_k_max)]
    context_block = build_context_block(contexts)
    memory_block = "\n".join(memory.get("content", "") for memory in (memories or []))[:2000]
    conversation_block = "\n".join(
        f"{message.get('role')}: {message.get('content')}" for message in (recent_messages or [])[-settings.chat_history_max_messages :]
    )
    language_block = language_instruction(language)
    user_prompt = f"""Instruksi bahasa:
{language_block}

Pertanyaan:
{question}

Konteks resmi yang boleh digunakan:
{context_block}

Memori aman untuk kontinuitas, bukan sumber resmi:
{memory_block}

Percakapan terbaru:
{conversation_block}

Kembalikan JSON valid sesuai format yang diminta.
Gunakan hanya URL dari konteks resmi.
Setiap kalimat faktual penting pada field answer harus mencantumkan marker sitasi bernomor seperti [1] atau [2].
Nomor marker harus sesuai urutan sources yang Anda kembalikan.
Jangan sertakan chain-of-thought, thought/action/observation, reasoning trace, atau tag <think> pada field mana pun.
Tulis isi field answer dengan rapi memakai Markdown: gunakan poin atau penomoran untuk langkah/daftar, **tebalkan** istilah penting, dan susun jawaban yang ringkas serta mudah dibaca."""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
    return messages, contexts


def finalize_generated_answer(
    content: str,
    contexts: list[dict],
    *,
    provider_used: str | None,
    model_used: str | None,
    memory_used: bool = False,
    provider_override: str | None = None,
) -> dict:
    """Verify + clean a raw LLM answer (server-side trust gate).

    Runs the JSON parse, citation validation, CGCV claim gate, extractive fallback,
    and output sanitiser. Applied identically whether ``content`` came from a server
    provider or from a browser LLM (Puter.js), so the browser path is just as gated.
    """
    settings = get_settings()
    try:
        payload = json.loads(_json_text(content))
    except json.JSONDecodeError:
        payload = {
            "answer": (content or "").strip(),
            "sources": _build_sources(contexts[:3]),
            "confidence": "medium",
            "not_found": False,
        }
    payload["provider_used"] = provider_used
    payload["model_used"] = model_used
    payload["memory_used"] = memory_used
    if not payload.get("sources"):
        payload["sources"] = _build_sources(contexts[:3])
    validated_payload = validate_citations(payload, contexts, require_citation_markers=True)
    if not validated_payload.get("not_found") and _cgcv_enabled():
        validated_payload = _apply_cgcv(validated_payload, contexts, provider_override)
    if validated_payload.get("not_found") and settings.llm_fallback_extractive:
        return extractive_fallback_payload(
            contexts=contexts,
            memory_used=memory_used,
            provider_used=provider_used,
            model_used=model_used,
            reason="provider_answer_missing_valid_citations",
        )
    validated_payload["answer"] = sanitize_answer(validated_payload.get("answer") or "")
    return validated_payload


def generate_answer(
    *,
    question: str,
    contexts: list[dict],
    recent_messages: list[dict] | None = None,
    memories: list[dict] | None = None,
    provider_override: str | None = None,
    language: str | None = None,
) -> dict:
    settings = get_settings()
    memory_used = bool(memories)
    if not contexts:
        return fallback_payload(memory_used=memory_used)

    messages, contexts = build_generation_messages(
        question=question,
        contexts=contexts,
        recent_messages=recent_messages,
        memories=memories,
        language=language,
    )
    max_retries = max(settings.llm_max_retries, 0)
    provider, response, last_error = _chat_with_failover(messages, provider_override, max_retries)

    if response is None:
        if settings.llm_fallback_extractive:
            return extractive_fallback_payload(
                contexts=contexts,
                memory_used=memory_used,
                provider_used=provider.provider_name if provider else normalize_provider(provider_override),
                model_used=provider.model if provider else None,
                reason=str(last_error) if last_error else "provider_unavailable",
            )
        if last_error:
            raise last_error
        raise RuntimeError("Provider returned no response.")

    return finalize_generated_answer(
        response.content,
        contexts,
        provider_used=response.provider_used,
        model_used=response.model_used,
        memory_used=memory_used,
        provider_override=provider_override,
    )
