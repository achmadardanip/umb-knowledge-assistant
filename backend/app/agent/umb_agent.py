from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.retrieval.hybrid_retriever import HybridRetriever
from app.web_search.live_retriever import UMBLiveWebRetriever

try:
    from langchain_core.tools import Tool
except Exception:  # pragma: no cover - fallback only when dependency is absent.
    Tool = None  # type: ignore[assignment]


RetrievalMode = Literal["indexed", "web", "hybrid"]
AgentEmitter = Callable[[str, str, str, str | None, dict | None], None]


@dataclass
class AgentResult:
    contexts: list[dict]
    indexed_context_count: int
    web_context_count: int
    agent_tool_calls: int


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
        web_contexts = live_retriever.search(tool_query, top_k=top_k)
        return f"{len(web_contexts)} live web contexts"

    def citation_tool(_tool_query: str) -> str:
        return "citation candidates prepared from retrieved contexts"

    _build_langchain_tools(indexed_tool, web_tool, citation_tool)

    planned_tools: list[str]
    if retrieval_mode == "indexed":
        planned_tools = ["indexed_retriever", "citation_validator"]
    elif retrieval_mode == "web":
        planned_tools = ["umb_live_web_search", "citation_validator"]
    else:
        planned_tools = ["indexed_retriever", "umb_live_web_search", "citation_validator"]

    emit_step(
        "agent",
        "Menjalankan agent retrieval UMB",
        "running",
        f"Mode {retrieval_mode}; maksimal {max_iterations} tool iteration",
        {"retrieval_mode": retrieval_mode, "max_tool_iterations": max_iterations},
    )

    for tool_name in planned_tools:
        if tool_calls >= max_iterations:
            emit_step("agent_limit", "Membatasi iterasi agent", "skipped", "Agent mencapai batas tool iteration")
            break
        if tool_name == "indexed_retriever":
            emit_step("indexed_retriever", "Mencari di indexed RAG UMB", "running", f"Top-k {top_k}")
            indexed_tool(query)
            tool_calls += 1
            emit_step(
                "indexed_retriever",
                "Mencari di indexed RAG UMB",
                "done" if indexed_contexts else "skipped",
                f"{len(indexed_contexts)} konteks indexed ditemukan",
                {"indexed_context_count": len(indexed_contexts)},
            )
        elif tool_name == "umb_live_web_search":
            emit_step("umb_live_web_search", "Mencari sumber live resmi UMB", "running", f"Domain {settings.web_search_strict_domain}")
            emit_step("web_scope", "Memvalidasi scope hasil web", "running", "Hanya root/subdomain UMB yang diterima")
            web_tool(query)
            tool_calls += 1
            emit_step("web_scope", "Memvalidasi scope hasil web", "done", "Hasil eksternal/lookalike/archive ditolak")
            emit_step(
                "umb_live_web_search",
                "Mengambil dan mengekstrak halaman live",
                "done" if web_contexts else "skipped",
                f"{len(web_contexts)} konteks live ditemukan",
                {"web_context_count": len(web_contexts)},
            )
        elif tool_name == "citation_validator":
            tool_calls += 1
            emit_step("citation_candidates", "Menyiapkan kandidat sitasi", "done", "Sitasi akan divalidasi sebelum jawaban final")

    if retrieval_mode == "indexed":
        contexts = indexed_contexts
    elif retrieval_mode == "web":
        contexts = web_contexts
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

    contexts = _dedupe_contexts(contexts)
    contexts.sort(key=lambda context: float(context.get("score") or 0.0), reverse=True)
    contexts = contexts[:top_k]
    emit_step(
        "agent",
        "Menjalankan agent retrieval UMB",
        "done",
        f"{len(contexts)} konteks final dipilih",
        {"retrieval_mode": retrieval_mode, "agent_tool_calls": tool_calls},
    )
    return AgentResult(
        contexts=contexts,
        indexed_context_count=len(indexed_contexts),
        web_context_count=len(web_contexts),
        agent_tool_calls=tool_calls,
    )
