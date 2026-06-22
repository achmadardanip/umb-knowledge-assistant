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
    try:
        resp = requests.post(
            f"{_BASE}/chat",
            json={"question": query, "include_retrieved_context": True},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # network/timeout/5xx -> failed test, never crash the run
        return {"error": f"chat request failed: {exc}"}

    chunks = data.get("retrieved_context") or []
    sources = data.get("sources") or []
    hosts = [(s.get("hostname") or "").lower() for s in sources if s.get("hostname")]
    official = bool(hosts) and all(h == _OFFICIAL_SUFFIX or h.endswith("." + _OFFICIAL_SUFFIX) for h in hosts)
    return {
        "output": data.get("answer") or "",
        "metadata": {
            "context": "\n\n".join(chunks)[:8000],
            "sources": sources,
            "official_source": official,
            "not_found": bool(data.get("not_found")),
        },
    }
