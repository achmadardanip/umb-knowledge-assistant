"""Promptfoo custom provider — calls the UMB structured entity/retrieval layer.

Deterministic (no LLM): given a query var it returns the top entity card text +
its official source URL, so Promptfoo can assert citation correctness, official-
source usage and entity accuracy reproducibly. Requires LOCAL_POSTGRES_MODE +
LOCAL_POSTGRES_URL in the environment (set by the CI workflow).
"""

from __future__ import annotations

import os
import sys

# make the backend importable
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "backend")))


def call_api(prompt, options, context):  # promptfoo python provider entrypoint
    from app.db.database import get_session_local
    from app.retrieval.entity_retriever import query_entities

    query = (context or {}).get("vars", {}).get("query") or prompt
    db = get_session_local()()
    try:
        results = query_entities(db, query)
    finally:
        db.close()
    top = results[0] if results else {}
    output = {
        "title": top.get("title"),
        "entity_type": top.get("entity_type"),
        "url": top.get("url"),
        "hostname": top.get("hostname"),
        "text": top.get("chunk_text"),
    }
    return {"output": output}
