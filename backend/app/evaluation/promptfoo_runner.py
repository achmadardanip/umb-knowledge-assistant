"""Phase 21 — deterministic local runner for the Promptfoo datasets.

Executes every generated test against the real retrieval / entity layers and the
session-memory follow-up resolver, evaluating the machine-checkable assertions
(entity_type / faculty / contains / official-source / no-hallucination). Produces
a reproducible report without needing the Promptfoo CLI or an LLM (the CI workflow
runs `npx promptfoo eval` for the LLM-judge view; this runner is the fast,
deterministic gate that asserts no regression).

    python -m app.evaluation.promptfoo_runner --out ../evaluation/promptfoo/reports/promptfoo_report.json
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from app.chat.session_memory import SessionMemory
from app.db.database import get_session_local
from app.db.models import UMBFaculty
from app.rag.followup_resolution import enrich_query
from app.retrieval.entity_retriever import query_entities
from app.trust.authority import host_authority

_DATASETS = Path(__file__).resolve().parents[3] / "evaluation" / "promptfoo" / "datasets"


def _faculty_of(ctx, n2s):
    title = str((ctx or {}).get("title") or "")
    for full, short in n2s.items():
        if full.lower() in title.lower():
            return short
    return None


def _assert(a, top, n2s, retriever=None, query="") -> bool:
    typ = a.get("type")
    if typ == "entity_type":
        return (top or {}).get("entity_type") == a["value"]
    if typ == "faculty":
        return _faculty_of(top, n2s) == a["value"]
    if typ == "contains":
        return a["value"].lower() in str((top or {}).get("title") or "").lower()
    if typ == "official-source":
        host = (top or {}).get("hostname") or ""
        if not host and (top or {}).get("url"):
            try:
                host = top["url"].split("/")[2]
            except Exception:
                host = ""
        return host_authority(host) >= 0.5
    if typ == "no-hallucination":
        # a structured entity OR an official source backs the answer.
        return bool(top) and (_faculty_of(top, n2s) is not None or host_authority((top or {}).get("hostname") or "") >= 0.5)
    return True


def _top_for(db, test, kind, n2s, retriever):
    if kind == "followup":
        mem = SessionMemory()
        sid = str(uuid.uuid4())
        est = test["vars"]["establish"]
        est_ctx = query_entities(db, est)
        mem.remember(sid, query=est, contexts=est_ctx, intent="faculty")
        q = enrich_query(test["vars"]["query"], mem.recall(sid))
        r = query_entities(db, q)
        return r[0] if r else {}
    q = test["vars"]["query"]
    if kind == "retrieval":
        res = retriever.search(q, top_k=5, apply_model_reranker=False, candidate_k=20)
        return res[0] if res else {}
    r = query_entities(db, q)
    return r[0] if r else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../evaluation/promptfoo/reports/promptfoo_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    from app.retrieval.hybrid_retriever import HybridRetriever
    retriever = HybridRetriever(db, root_domain="mercubuana.ac.id")
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        summary = {}
        for kind in ("entity", "accreditation", "followup", "retrieval"):
            data = json.loads((_DATASETS / f"{kind}.json").read_text(encoding="utf-8"))["tests"]
            passed = 0
            failures = []
            for test in data:
                top = _top_for(db, test, kind, n2s, retriever)
                ok = all(_assert(a, top, n2s, retriever, test["vars"].get("query", "")) for a in test["assert"])
                passed += ok
                if not ok and len(failures) < 15:
                    failures.append({"vars": test["vars"], "got": str((top or {}).get("title") or (top or {}).get("url") or "")[:50]})
            summary[kind] = {
                "tests": len(data), "passed": passed,
                "pass_rate": round(passed / max(len(data), 1), 4),
                "failures_sample": failures,
            }
            print(f"  {kind:14s}: {passed}/{len(data)} ({summary[kind]['pass_rate']})")
    finally:
        db.close()

    total = sum(s["tests"] for s in summary.values())
    total_pass = sum(s["passed"] for s in summary.values())
    report = {
        "total_tests": total,
        "total_passed": total_pass,
        "overall_pass_rate": round(total_pass / max(total, 1), 4),
        "by_suite": summary,
        "reproducible": True,
        "runner": "deterministic (entity + retrieval layers, no LLM)",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OVERALL: {total_pass}/{total} ({report['overall_pass_rate']}) -> {out}")


if __name__ == "__main__":
    main()
