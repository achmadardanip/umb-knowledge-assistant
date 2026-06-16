from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.ingestion.umb_content import canonicalize_umb_url
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.reranker import model_rerank_contexts
from app.trust.va_jit import va_jit_reverify
from app.web_search.live_retriever import UMBLiveWebRetriever

try:
    from langchain_core.tools import Tool
except Exception:  # pragma: no cover - fallback only when dependency is absent.
    Tool = None  # type: ignore[assignment]


RetrievalMode = Literal["indexed", "web", "hybrid"]
AgentEmitter = Callable[[str, str, str, str | None, dict | None], None]
logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    contexts: list[dict]
    indexed_context_count: int
    web_context_count: int
    agent_tool_calls: int
    retrieval_fallback_used: bool = False
    retrieval_warnings: list[str] | None = None
    gate_debug: dict | None = None


def _dedupe_contexts(contexts: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for context in contexts:
        raw_url = context.get("url")
        try:
            canonical_url = canonicalize_umb_url(raw_url) if raw_url else raw_url
        except (TypeError, ValueError):
            canonical_url = raw_url
        key = (
            canonical_url,
            context.get("page_number"),
            context.get("slide_number"),
            context.get("sheet_name"),
            context.get("row_range"),
            context.get("timestamp_start"),
            context.get("timestamp_end"),
            (context.get("chunk_text") or "")[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        if canonical_url and canonical_url != raw_url:
            context = {**context, "url": canonical_url}
        deduped.append(context)
    return deduped


def _build_langchain_tools(indexed_tool, web_tool, citation_tool) -> list:
    """Expose the retrieval operations as LangChain tools.

    The orchestration below intentionally logs only tool names and counts, not
    model thoughts. This keeps the ReAct-style loop operational and auditable.
    """

    if Tool is None:
        return []
    return [
        Tool.from_function(indexed_tool, name="indexed_retriever", description="Search indexed official UMB chunks."),
        Tool.from_function(web_tool, name="umb_live_web_search", description="Search and fetch live official UMB pages."),
        Tool.from_function(citation_tool, name="citation_validator", description="Validate that citations point to retrieved UMB sources."),
    ]


def _va_jit_enabled() -> bool:
    return get_settings().va_jit_enabled


def _maybe_va_jit(query: str, contexts: list[dict], live_retriever, emit_step) -> list[dict]:
    """Trigger a bounded live re-verification for volatile, stale facts (VA-JIT).

    Fresh re-fetched contexts (freshness=1.0) are surfaced above the stale
    indexed evidence; CGCV downstream then re-verifies claims against them — the
    conformal buy-back, realized by sequencing on the shared context set.
    """
    settings = get_settings()
    today = datetime.now(timezone.utc).date().isoformat()

    def fetcher(reverify_query: str, *, budget: int) -> list[dict]:
        try:
            fresh = live_retriever.search(reverify_query, top_k=budget)
        except Exception:
            return []
        for context in fresh:
            context["freshness"] = 1.0
            context["last_verified"] = today
        return fresh

    fresh = va_jit_reverify(
        query,
        contexts,
        fetcher=fetcher,
        budget=settings.va_jit_budget,
        volatility_threshold=settings.va_jit_volatility_threshold,
        freshness_threshold=settings.va_jit_freshness_threshold,
    )
    if not fresh:
        return contexts
    top_score = max((float(context.get("score") or 0.0) for context in contexts), default=0.0)
    for context in fresh:
        context["score"] = top_score + 1.0
    emit_step(
        "va_jit",
        "Verifikasi langsung fakta dinamis",
        "done",
        f"{len(fresh)} sumber resmi diverifikasi ulang secara live",
        {"va_jit_count": len(fresh)},
    )
    return _dedupe_contexts(fresh + contexts)


def _kb_contexts_sufficient(indexed_contexts: list[dict], top_k: int, settings) -> bool:
    """KB-first gate: return True when indexed retrieval is strong enough that the
    live-web fallback can be skipped (keeps well-covered questions fast and grounded
    in the indexed KB; live web is reserved for genuine gaps). ``getattr`` defaults
    keep monkeypatched test settings that omit the knobs working."""
    if not indexed_contexts:
        return False
    min_contexts = getattr(settings, "web_fallback_min_contexts", 3)
    min_score = getattr(settings, "web_fallback_min_score", 1.2)
    if len(indexed_contexts) < min(top_k, min_contexts):
        return False
    return float(indexed_contexts[0].get("score") or 0.0) >= min_score


def run_umb_agent(
    *,
    db: Session,
    query: str,
    retrieval_mode: RetrievalMode,
    top_k: int,
    root_domain: str,
    emit: AgentEmitter | None = None,
    indexed_retriever_cls=HybridRetriever,
    match_query: str | None = None,
    intent: str | None = None,
) -> AgentResult:
    settings = get_settings()
    # ``query`` is the (possibly context-augmented) vector-retrieval query.
    # ``match_query`` is the bare user question used for the deterministic
    # structured layers (FAQ / entity / typed-graph) and intent routing — their
    # exact matching degrades when topic/history text is appended to the query.
    structured_query = match_query or query
    max_iterations = max(1, settings.agent_max_tool_iterations)
    contexts: list[dict] = []
    indexed_contexts: list[dict] = []
    faq_contexts: list[dict] = []
    entity_contexts: list[dict] = []
    graph_contexts: list[dict] = []
    web_contexts: list[dict] = []
    retrieval_warnings: list[str] = []
    retrieval_fallback_used = False
    tool_calls = 0

    def emit_step(step_id: str, label: str, status: str, detail: str | None = None, metadata: dict | None = None) -> None:
        if emit:
            emit(step_id, label, status, detail, metadata)

    indexed_retriever = indexed_retriever_cls(db, root_domain=root_domain)
    live_retriever = UMBLiveWebRetriever()

    def indexed_tool(tool_query: str) -> str:
        nonlocal indexed_contexts
        if settings.reranker_enabled:
            indexed_contexts = indexed_retriever.search(
                tool_query,
                top_k=top_k,
                apply_model_reranker=False,
                candidate_k=settings.reranker_candidate_k,
            )
        else:
            indexed_contexts = indexed_retriever.search(tool_query, top_k=top_k)
        return f"{len(indexed_contexts)} indexed contexts"

    def web_tool(tool_query: str) -> str:
        nonlocal web_contexts
        try:
            web_contexts = live_retriever.search(tool_query, top_k=top_k)
        except Exception as exc:
            web_contexts = []
            retrieval_warnings.append(str(exc))
            logger.info("Live web retrieval skipped: %s", exc)
        return f"{len(web_contexts)} live web contexts"

    def citation_tool(_tool_query: str) -> str:
        return "citation candidates prepared from retrieved contexts"

    _build_langchain_tools(indexed_tool, web_tool, citation_tool)

    emit_step(
        "agent",
        "Menyiapkan retrieval UMB",
        "running",
        f"Mode {retrieval_mode}; maksimal {max_iterations} langkah alat",
        {"retrieval_mode": retrieval_mode, "max_tool_iterations": max_iterations},
    )

    def can_call_tool() -> bool:
        return tool_calls < max_iterations

    def run_faq_lookup() -> None:
        """FAQ-first: match the query against curated canonical FAQs. Runs before
        entity lookup and vector search; matches rank above all other contexts."""
        nonlocal faq_contexts
        try:
            from app.retrieval.faq_retriever import match_faq

            faq_contexts = match_faq(db, structured_query)
        except Exception as exc:
            faq_contexts = []
            logger.debug("FAQ lookup skipped: %s", exc)
        if faq_contexts:
            via = faq_contexts[0].get("faq_matched_via", "match")
            emit_step(
                "faq_lookup",
                "Mencocokkan FAQ kanonik",
                "done",
                f"{len(faq_contexts)} FAQ resmi cocok ({via})",
                {"faq_count": len(faq_contexts), "matched_via": via},
            )
        else:
            emit_step(
                "faq_lookup",
                "Mencocokkan FAQ kanonik",
                "skipped",
                "Tidak ada FAQ kanonik yang cocok",
                {"faq_count": 0},
            )

    def run_entity_lookup() -> None:
        nonlocal entity_contexts
        try:
            from app.retrieval.entity_retriever import query_entities

            entity_contexts = query_entities(db, structured_query, root_domain=root_domain)
        except Exception as exc:
            entity_contexts = []
            logger.debug("Entity lookup skipped: %s", exc)
        if entity_contexts:
            emit_step(
                "entity_lookup",
                "Lookup entitas terstruktur",
                "done",
                f"{len(entity_contexts)} entitas ditemukan dari tabel terstruktur",
                {"entity_count": len(entity_contexts)},
            )
        else:
            emit_step(
                "entity_lookup",
                "Lookup entitas terstruktur",
                "skipped",
                "Tidak ada entitas relevan ditemukan",
                {"entity_count": 0},
            )

    def run_typed_graph_lookup() -> None:
        """Typed GraphRAG: walk typed relations over the entity tables to produce
        deterministic relational-answer contexts (e.g. a faculty's program list).
        ``getattr`` defaults keep monkeypatched test settings (which omit the knobs)
        working."""
        nonlocal graph_contexts
        if not getattr(settings, "typed_graph_enabled", True):
            return
        try:
            from app.graph.typed_graph_store import typed_expansion_from_db

            graph_contexts = typed_expansion_from_db(
                db,
                structured_query,
                root_domain=root_domain,
                limit=getattr(settings, "typed_graph_expansion_top_k", 3),
                path=getattr(settings, "typed_graph_path", None),
            )
        except Exception as exc:
            graph_contexts = []
            logger.debug("Typed graph lookup skipped: %s", exc)
        if graph_contexts:
            emit_step(
                "typed_graph",
                "Menelusuri relasi entitas tertipe",
                "done",
                f"{len(graph_contexts)} relasi entitas ditemukan",
                {"graph_relation_count": len(graph_contexts)},
            )

    def _merge_structured_contexts() -> None:
        """Prepend FAQ + entity + typed-graph contexts into indexed_contexts after
        run_indexed completes (FAQ first, then entities, then graph relations, then
        indexed chunks).

        Must be called after run_indexed() because indexed_tool() assigns a fresh
        list to indexed_contexts, which would overwrite any premature merge.
        """
        nonlocal indexed_contexts
        if faq_contexts or entity_contexts or graph_contexts:
            indexed_contexts = faq_contexts + entity_contexts + graph_contexts + indexed_contexts

    def run_indexed(*, fallback: bool = False) -> None:
        nonlocal tool_calls
        if not can_call_tool():
            emit_step("agent_limit", "Membatasi langkah retrieval", "skipped", "Batas langkah alat tercapai")
            return
        step_id = "indexed_fallback" if fallback else "indexed_retriever"
        label = "Mencari sumber indexed resmi UMB"
        emit_step(step_id, label, "running", f"Top-k {top_k}")
        indexed_tool(query)
        tool_calls += 1
        emit_step(
            step_id,
            label,
            "done" if indexed_contexts else "skipped",
            f"{len(indexed_contexts)} konteks indexed ditemukan",
            {"indexed_context_count": len(indexed_contexts), "fallback": fallback},
        )

    def run_web() -> None:
        nonlocal tool_calls
        if tool_calls >= max_iterations:
            emit_step("agent_limit", "Membatasi langkah retrieval", "skipped", "Batas langkah alat tercapai")
            return
        emit_step("umb_live_web_search", "Mencari sumber live resmi UMB", "running", f"Domain {settings.web_search_strict_domain}")
        emit_step("web_scope", "Memvalidasi scope hasil web", "running", "Hanya root/subdomain UMB yang diterima")
        web_tool(query)
        tool_calls += 1
        emit_step("web_scope", "Memvalidasi scope hasil web", "done", "Hasil eksternal/lookalike/archive ditolak")
        status = "done" if web_contexts else ("error" if retrieval_warnings else "skipped")
        emit_step(
            "umb_live_web_search",
            "Mengambil dan mengekstrak halaman live",
            status,
            f"{len(web_contexts)} konteks live ditemukan",
            {"web_context_count": len(web_contexts), "warning": retrieval_warnings[-1] if retrieval_warnings else None},
        )

    run_faq_lookup()
    run_entity_lookup()
    run_typed_graph_lookup()

    if retrieval_mode == "indexed":
        run_indexed()
        _merge_structured_contexts()
    elif retrieval_mode == "web":
        run_web()
        if not web_contexts:
            retrieval_fallback_used = True
            run_indexed(fallback=True)
            _merge_structured_contexts()
    else:
        run_indexed()
        _merge_structured_contexts()
        # Confidence Check: gate the billed Tavily live fallback on retrieval
        # confidence. FAQ → Entity → Graph → Hybrid → confidence → (only if low) Tavily.
        from app.rag.discovery_cache import evaluate_confidence, was_recently_discovered

        confidence_score, confidence_sufficient = evaluate_confidence(indexed_contexts, root_domain=root_domain)
        kb_ok = _kb_contexts_sufficient(indexed_contexts, top_k, settings)
        recently = (
            was_recently_discovered(db, structured_query)
            if not (kb_ok or confidence_sufficient)
            else False
        )
        emit_step(
            "confidence_check",
            "Mengevaluasi keyakinan retrieval",
            "done",
            f"Confidence {confidence_score:.2f}; {'memadai' if (kb_ok or confidence_sufficient or recently) else 'rendah → fallback live'}",
            {"confidence": round(confidence_score, 3), "sufficient": bool(kb_ok or confidence_sufficient or recently)},
        )
        if kb_ok or confidence_sufficient or recently:
            reason = (
                "Sudah pernah ditemukan via web & terindeks; pakai KB"
                if recently
                else "Konteks resmi sudah memadai; live web tidak diperlukan"
            )
            emit_step(
                "umb_live_web_search",
                "Melewati pencarian live",
                "skipped",
                reason,
                {"web_context_count": 0, "indexed_context_count": len(indexed_contexts), "confidence": round(confidence_score, 3)},
            )
        else:
            run_web()
        if retrieval_warnings and indexed_contexts:
            retrieval_fallback_used = True
            emit_step(
                "web_to_indexed_fallback",
                "Memakai sumber indexed karena live web tidak tersedia",
                "done",
                "Jawaban tetap memakai konteks resmi yang sudah diindeks",
                {"retrieval_fallback_used": True},
            )

    if can_call_tool():
        tool_calls += 1
        emit_step("citation_candidates", "Menyiapkan kandidat sitasi", "done", "Sitasi akan divalidasi sebelum jawaban final")

    if retrieval_mode == "indexed":
        contexts = indexed_contexts
    elif retrieval_mode == "web":
        contexts = web_contexts or indexed_contexts
    else:
        emit_step("agent_merge", "Menggabungkan konteks indexed dan live", "running")
        contexts = indexed_contexts + web_contexts
        emit_step(
            "agent_merge",
            "Menggabungkan konteks indexed dan live",
            "done",
            f"{len(indexed_contexts)} indexed + {len(web_contexts)} live",
            {"indexed_context_count": len(indexed_contexts), "web_context_count": len(web_contexts)},
        )

    # Intent gate (collaborator's trustworthy-answers layer): junk contexts must not
    # satisfy retrieval. Hard-filter off-intent vector/web sources, then trigger the
    # live fallback on "no answerable intent-matched contexts" — not on "no contexts" —
    # even in indexed mode. The v3 deterministic structured layer (FAQ / entity / typed
    # graph) is exempt from hard rejection: those retrievers already enforce intent via
    # their own matching + intent_router demotion, so they stay pinned and high-precision.
    gate_debug: dict | None = None
    if intent:
        from app.retrieval.intent_gate import (
            gate_contexts,
            live_query_for_intent,
            should_trigger_live_fallback,
        )

        _structured_types = {"faq", "entity", "graph"}
        exempt = [c for c in contexts if c.get("source_type") in _structured_types]
        gateable = [c for c in contexts if c.get("source_type") not in _structured_types]
        candidates_before = len(gateable)
        kept, rejected = gate_contexts(query, intent, gateable)
        reject_reasons: dict[str, int] = {}
        for item in rejected:
            reason_key = str(item.get("_reject_reason") or "unknown").split(":")[0]
            reject_reasons[reason_key] = reject_reasons.get(reason_key, 0) + 1
        contexts = exempt + kept
        emit_step(
            "intent_gate",
            "Memfilter sumber sesuai intent pertanyaan",
            "done" if kept or exempt or not candidates_before else "running",
            f"{len(kept)}/{candidates_before} kandidat lolos filter intent '{intent}'",
            {"intent": intent, "kept": len(kept), "rejected": len(rejected), "reject_reasons": reject_reasons},
        )

        trigger, fallback_reason = should_trigger_live_fallback(intent, exempt + kept)
        live_accepted = 0
        live_found = 0
        if (
            trigger
            and getattr(settings, "enable_live_fallback_on_low_answerability", True)
            and not web_contexts
        ):
            live_query = live_query_for_intent(query, intent)
            emit_step(
                "fallback_retrieval",
                "Konteks KB tidak menjawab intent — mencari sumber live resmi",
                "running",
                f"Alasan: {fallback_reason}",
            )
            try:
                fallback_web = live_retriever.search(live_query, top_k=top_k)
            except Exception as exc:
                fallback_web = []
                retrieval_warnings.append(str(exc))
                logger.info("Intent fallback live retrieval skipped: %s", exc)
            live_found = len(fallback_web)
            kept_web, rejected_web = gate_contexts(query, intent, fallback_web)
            live_accepted = len(kept_web)
            if kept_web:
                web_contexts = list(kept_web)
                contexts = contexts + kept_web
            retrieval_fallback_used = True
            emit_step(
                "fallback_retrieval",
                "Konteks KB tidak menjawab intent — mencari sumber live resmi",
                "done" if kept_web else "skipped",
                f"{live_accepted}/{live_found} sumber live lolos filter intent",
                {
                    "fallback_reason": fallback_reason,
                    "live_results": live_found,
                    "live_results_accepted": live_accepted,
                    "live_results_rejected": len(rejected_web),
                },
            )
        gate_debug = {
            "intent": intent,
            "retrieved_candidates": candidates_before,
            "rejected_candidates": len(rejected),
            "reject_reasons": reject_reasons,
            "kept_candidates": len(kept),
            "fallback_triggered": bool(trigger),
            "fallback_reason": fallback_reason,
            "live_results": live_found,
            "live_results_accepted": live_accepted,
        }

    graph_settings = get_settings()
    if graph_settings.graph_rag_enabled and retrieval_mode != "web" and contexts:
        try:
            from app.graph.graph_store import expansion_contexts, load_graph

            graph = load_graph(graph_settings.graph_path)
            if graph is not None:
                exclude_ids = {c.get("chunk_id") for c in contexts if c.get("chunk_id")}
                graph_ctx = expansion_contexts(
                    db,
                    query,
                    graph,
                    root_domain=root_domain,
                    limit=graph_settings.graph_expansion_top_k,
                    exclude_chunk_ids=exclude_ids,
                )
                graph_found = len(graph_ctx)
                graph_rejected = 0
                if graph_ctx and intent and getattr(graph_settings, "enable_graph_intent_filter", True):
                    from app.retrieval.intent_gate import gate_contexts as _gate_graph

                    graph_ctx, graph_dropped = _gate_graph(query, intent, graph_ctx)
                    graph_rejected = len(graph_dropped)
                if gate_debug is not None:
                    gate_debug["graph_contexts_found"] = graph_found
                    gate_debug["graph_contexts_rejected"] = graph_rejected
                    gate_debug["graph_contexts_final"] = len(graph_ctx)
                if graph_ctx:
                    contexts = contexts + graph_ctx
                    emit_step(
                        "graph_rag",
                        "Memperluas konteks via knowledge graph",
                        "done",
                        f"{len(graph_ctx)} konteks tambahan dari relasi entitas ({graph_rejected} ditolak filter intent)",
                        {"graph_context_count": len(graph_ctx), "graph_contexts_rejected": graph_rejected},
                    )
        except Exception as exc:  # graph is best-effort; never break retrieval
            logging.getLogger(__name__).warning("GraphRAG expansion skipped: %s", exc)

    contexts = _dedupe_contexts(contexts)
    if _va_jit_enabled() and contexts:
        contexts = _maybe_va_jit(query, contexts, live_retriever, emit_step)

    # v3 P2: intent-aware host hard filter — boost on-intent hosts, heavily
    # penalise an official-but-off-intent vector chunk (so a SIA-login query can
    # never be answered by a tuition page). Uses the bare question for intent.
    if contexts:
        from app.rag.intent_router import apply_intent_host_filter, detect_intent

        _intent = detect_intent(structured_query)
        apply_intent_host_filter(structured_query, contexts, intent=_intent, root_domain=root_domain)
        emit_step("intent_host_filter", "Filter host sesuai intent", "done",
                  f"Intent {_intent}: host kompatibel diprioritaskan", {"intent": _intent})

    # Structured contexts (FAQ, entity, typed-graph relations) are deterministic,
    # high-precision, and pre-scored; keep them pinned above the vector results.
    # The reranker (a passage cross-encoder) only reorders the chunk/vector
    # candidates — this realizes the pipeline order
    # FAQ → Entity → Graph → Vector → Reranker.
    # A structured context is pinned only if it is NOT intent-demoted. An
    # intent-demoted entity/graph context (fired on an incidental entity name in
    # a topical question) joins the rerankable pool and competes by score, so it
    # can't bury the topical FAQ/vector source. (v2 entity over-firing fix.)
    _structured_types = {"faq", "entity", "graph"}
    structured = [c for c in contexts if c.get("source_type") in _structured_types and not c.get("intent_demoted")]
    rerankable = [c for c in contexts if c.get("source_type") not in _structured_types or c.get("intent_demoted")]
    structured.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)

    if settings.reranker_enabled and rerankable:
        emit_step(
            "model_reranker",
            "Mengurutkan ulang kandidat multilingual",
            "running",
            f"Maksimal {settings.reranker_candidate_k} kandidat",
        )
        rerankable = model_rerank_contexts(query, rerankable, root_domain=root_domain)
        reranker_used = any(context.get("reranker_used") for context in rerankable)
        emit_step(
            "model_reranker",
            "Mengurutkan ulang kandidat multilingual",
            "done" if reranker_used else "skipped",
            "BGE reranker diterapkan" if reranker_used else "Ranking baseline dipertahankan",
            {"reranker_used": reranker_used, "reranker_model": settings.reranker_model},
        )
    else:
        rerankable.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)
    contexts = (structured + rerankable)[:top_k]
    emit_step(
        "agent",
        "Menyiapkan retrieval UMB",
        "done",
        f"{len(contexts)} konteks final dipilih",
        {
            "retrieval_mode": retrieval_mode,
            "agent_tool_calls": tool_calls,
            "retrieval_fallback_used": retrieval_fallback_used,
        },
    )
    return AgentResult(
        contexts=contexts,
        indexed_context_count=len(indexed_contexts),
        web_context_count=len(web_contexts),
        agent_tool_calls=tool_calls,
        retrieval_fallback_used=retrieval_fallback_used,
        retrieval_warnings=retrieval_warnings,
        gate_debug=gate_debug,
    )
