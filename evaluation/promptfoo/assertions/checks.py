"""Phase 21 — reusable Promptfoo python assertions for the UMB structured provider.

Each function receives the provider ``output`` dict and the test's expected value;
it returns a promptfoo GradingResult ({pass, score, reason}). These mirror the
checks the deterministic runner enforces (official-source / entity-type / faculty /
contains / no-hallucination) so the two paths agree.
"""

from __future__ import annotations

import re

_OFFICIAL = re.compile(r"(^|\.)mercubuana\.ac\.id$")


def _host(output: dict) -> str:
    h = (output or {}).get("hostname") or ""
    if not h and (output or {}).get("url"):
        try:
            h = output["url"].split("/")[2]
        except Exception:
            h = ""
    return h


def official_source(output, context=None):
    h = _host(output)
    ok = bool(_OFFICIAL.search(h))
    return {"pass": ok, "score": 1 if ok else 0, "reason": f"source host: {h or '(none)'}"}


def entity_type(output, expected):
    ok = (output or {}).get("entity_type") == expected
    return {"pass": ok, "score": 1 if ok else 0, "reason": f"entity_type={output.get('entity_type')}"}


def contains(output, expected):
    ok = expected.lower() in str((output or {}).get("title") or "").lower()
    return {"pass": ok, "score": 1 if ok else 0, "reason": f"title={output.get('title')}"}


def no_hallucination(output, context=None):
    ok = bool((output or {}).get("title")) and bool(_OFFICIAL.search(_host(output)))
    return {"pass": ok, "score": 1 if ok else 0, "reason": "answer backed by official entity" if ok else "unbacked"}
