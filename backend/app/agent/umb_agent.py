from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.retrieval.hybrid_retriever import HybridRetriever
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


def _dedupe_contexts(contexts: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for context in contexts:
        key = (
            context.get("url"),
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


def run_umb_agent(
    *,
    db: Session,
    query: str,
    retrieval_mode: RetrievalMode,
    top_k: int,
    root_domain: str,
    emit: AgentEmitter | None = None,
    indexed_retriever_cls=HybridRetriever,
) -> AgentResult:
    settings = get_settings()
    max_iterations = max(1, settings.agent_max_tool_iterations)
    contexts: list[dict] = []
    indexed_contexts: list[dict] = []
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

    if retrieval_mode == "indexed":
        run_indexed()
    elif retrieval_mode == "web":
        run_web()
        if not web_contexts:
            retrieval_fallback_used = True
            run_indexed(fallback=True)
    else:
        run_indexed()
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
                if graph_ctx:
                    contexts = contexts + graph_ctx
                    emit_step(
                        "graph_rag",
                        "Memperluas konteks via knowledge graph",
                        "done",
                        f"{len(graph_ctx)} konteks tambahan dari relasi entitas",
                        {"graph_context_count": len(graph_ctx)},
                    )
        except Exception as exc:  # graph is best-effort; never break retrieval
            logging.getLogger(__name__).warning("GraphRAG expansion skipped: %s", exc)

    contexts = _dedupe_contexts(contexts)
    if _va_jit_enabled() and contexts:
        contexts = _maybe_va_jit(query, contexts, live_retriever, emit_step)
    contexts.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)
    contexts = contexts[:top_k]
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
    )
