#!/usr/bin/env python3
"""Phase 15 P7 — local deployment startup validation.

Verifies the running local stack answers on the documented endpoints. Run after:

    docker compose -f docker-compose.local.yml up -d        # or the ad-hoc :5433 container
    cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000
    cd frontend && npm run dev

Usage:
    python scripts/validate_local.py                 # health + stats + providers (fast)
    python scripts/validate_local.py --full          # also exercises the chat/retrieval endpoint
    python scripts/validate_local.py --base http://localhost:8000 --frontend http://localhost:3000

Exit code 0 = all required checks passed, 1 = at least one failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

_OK = "PASS"
_NO = "FAIL"


def _get(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def _post(url: str, payload: dict, timeout: float = 180.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--frontend", default="http://localhost:3000")
    ap.add_argument("--full", action="store_true", help="also exercise the chat/retrieval endpoint (slow on CPU)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    results: list[tuple[str, bool, str]] = []

    def check(name: str, fn):
        try:
            ok, detail = fn()
            results.append((name, ok, detail))
        except urllib.error.URLError as e:
            results.append((name, False, f"unreachable: {e}"))
        except Exception as e:  # noqa: BLE001
            results.append((name, False, f"error: {e}"))

    def _health():
        s, j = _get(f"{base}/health")
        ok = s == 200 and (isinstance(j, dict) and (j.get("status") in {"ok", "healthy"} or j.get("ok")))
        return ok, f"status={s} body={j if isinstance(j, str) else json.dumps(j)[:80]}"

    def _stats():
        s, j = _get(f"{base}/stats")
        chunks = (j or {}).get("chunks") if isinstance(j, dict) else None
        ok = s == 200 and isinstance(chunks, int) and chunks > 0
        return ok, f"status={s} chunks={chunks} entities={(j or {}).get('entities') if isinstance(j, dict) else '?'}"

    def _providers():
        s, j = _get(f"{base}/settings/providers")
        ok = s == 200 and isinstance(j, dict) and bool(j.get("providers"))
        return ok, f"status={s} default={(j or {}).get('default_provider') if isinstance(j, dict) else '?'}"

    def _frontend():
        s, _ = _get(args.frontend.rstrip("/"), timeout=8.0)
        return s == 200, f"status={s}"

    def _chat():
        s, j = _post(f"{base}/chat", {
            "anonymous_session_id": "validate-local",
            "question": "Siapa dekan FEB?",
            "top_k": 5,
            "memory_enabled": False,
        })
        srcs = (j or {}).get("sources") if isinstance(j, dict) else None
        ok = s == 200 and isinstance(j, dict) and bool(j.get("answer"))
        return ok, f"status={s} answer_len={len((j or {}).get('answer','')) if isinstance(j, dict) else 0} sources={len(srcs or [])}"

    check("GET /health", _health)
    check("GET /stats", _stats)
    check("GET /settings/providers", _providers)
    check("frontend /", _frontend)  # informational; frontend may not be running
    if args.full:
        check("POST /chat (retrieval)", _chat)

    print("\nUMB local deployment validation")
    print("=" * 48)
    required_failed = 0
    for name, ok, detail in results:
        tag = _OK if ok else _NO
        print(f"  [{tag}] {name:26s} {detail}")
        # frontend is informational, not required for backend health.
        if not ok and name != "frontend /":
            required_failed += 1
    print("=" * 48)
    if required_failed:
        print(f"{required_failed} required check(s) FAILED")
        return 1
    print("all required checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
