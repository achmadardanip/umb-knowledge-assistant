"""Promptfoo provider — calls the real UMB /chat endpoint for RAG monitoring.

Returns the generated answer as `output` plus the retrieved context, citation
sources, and an official-source flag in `metadata`, so Promptfoo can grade
context-faithfulness and check official sourcing against the live chatbot.
"""
from __future__ import annotations

import os

import requests

_BASE = os.getenv("UMB_CHAT_BASE_URL", "http://localhost:8000").rstrip("/")
_TIMEOUT = int(os.getenv("UMB_CHAT_TIMEOUT", "240"))
_OFFICIAL_SUFFIX = os.getenv("UMB_OFFICIAL_DOMAIN", "mercubuana.ac.id")


def call_api(prompt, options, context):  # promptfoo python provider entrypoint
    query = (context or {}).get("vars", {}).get("query") or prompt
    # Per-provider config lets us run the SAME endpoint under two retrieval modes
    # (indexed vs hybrid) as two columns, which Promptfoo needs to render charts.
    config = (options or {}).get("config") or {}
    mode = config.get("retrieval_mode", "hybrid")
    body = {"question": query, "include_retrieved_context": True, "retrieval_mode": mode}
    # Optional answer-model override for the "brain comparison" audit.
    if config.get("answer_model"):
        body["answer_model"] = config["answer_model"]
    try:
        resp = requests.post(f"{_BASE}/chat", json=body, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network/timeout/5xx -> failed test, never crash the run
        return {"error": f"chat request failed: {exc}"}

    chunks = data.get("retrieved_context") or []
    sources = data.get("sources") or []
    hosts = [(s.get("hostname") or "").lower() for s in sources if s.get("hostname")]
    official = bool(hosts) and all(h == _OFFICIAL_SUFFIX or h.endswith("." + _OFFICIAL_SUFFIX) for h in hosts)

    # Faithfulness must be graded against the grounding the pipeline ACTUALLY used.
    # The UMB pipeline is FAQ -> Entity -> GraphRAG -> Vector -> Reranker, so an answer
    # correctly sourced from the FAQ/Entity/Graph layers carries NO vector chunks in
    # `retrieved_context`. Grading such a (correct, cited) answer against an empty
    # context yields a false 0.00 / "Context is required" error. To grade the real
    # grounding, fall back to the citation evidence the answer was built from
    # (source title + snippet + url) whenever the vector context is thin. This does
    # not weaken the assertion — it gives the judge the evidence it is meant to check.
    context_parts: list[str] = [c for c in chunks if c]
    if len(" ".join(context_parts)) < 200:
        for s in sources:
            frag = " — ".join(
                str(s.get(k) or "").strip()
                for k in ("title", "snippet", "chunk_text", "url")
                if s.get(k)
            )
            if frag:
                context_parts.append(frag)
    context = "\n\n".join(context_parts)[:8000]

    return {
        "output": data.get("answer") or "",
        "metadata": {
            # Non-empty placeholder so context-faithfulness never aborts with the
            # "Context is required" invariant on a grounded-but-chunkless answer.
            "context": context or "(no retrieved context — answer is a refusal or out-of-scope)",
            "sources": sources,
            "official_source": official,
            "not_found": bool(data.get("not_found")),
            "grounded": bool(sources) and not data.get("not_found"),
        },
    }
