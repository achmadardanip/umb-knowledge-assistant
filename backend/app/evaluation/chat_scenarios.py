"""End-to-end chat validation (Task 2). POSTs real questions to the live /chat
endpoint (the same call the frontend makes) and records, per question:
answer, sources, FAQ/entity/graph/vector hits, citation quality, latency, origin.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    ("admissions", "Bagaimana cara mendaftar PMB di Universitas Mercu Buana?"),
    ("admissions", "Apa saja syarat pendaftaran mahasiswa baru di UMB?"),
    ("tuition", "Berapa biaya kuliah untuk program Teknik Informatika di UMB?"),
    ("programs", "Program studi apa saja yang ada di Fakultas Teknik UMB?"),
    ("calendar", "Di mana saya bisa melihat kalender akademik UMB?"),
    ("scholarships", "Beasiswa apa saja yang tersedia di UMB?"),
    ("campus", "Di mana lokasi kampus Meruya Universitas Mercu Buana?"),
    ("sia", "Bagaimana cara mengakses SIA UMB?"),
    ("sso", "Apa portal SSO resmi Universitas Mercu Buana?"),
]

_LAYER_STEPS = {
    "faq_lookup": "FAQ",
    "entity_lookup": "Entity",
    "typed_graph": "GraphRAG",
    "indexed_retriever": "Vector",
    "umb_live_web_search": "LiveWeb",
}


def _origin(steps: list[dict], sources: list[dict]) -> str:
    """Infer which layer produced the grounding evidence from the visible steps."""
    done = {s.get("id"): s.get("status") for s in steps}
    if done.get("faq_lookup") == "done":
        return "FAQ"
    if done.get("entity_lookup") == "done":
        return "Entity"
    if done.get("typed_graph") == "done":
        return "GraphRAG"
    if sources:
        return "Vector/Indexed"
    return "LLM-prior/none"


def run() -> dict:
    out = {"base": BASE, "results": []}
    with httpx.Client(timeout=300.0) as client:
        # one shared anonymous session
        anon = f"validation-{int(time.time())}"
        for category, question in SCENARIOS:
            started = time.perf_counter()
            try:
                resp = client.post(
                    f"{BASE}/chat",
                    json={"question": question, "anonymous_session_id": anon, "retrieval_mode": "hybrid", "top_k": 5},
                )
                latency = time.perf_counter() - started
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                out["results"].append({"category": category, "question": question, "error": str(exc),
                                       "latency_s": round(time.perf_counter() - started, 1)})
                print(f"[ERR] {category}: {exc}")
                continue

            steps = data.get("visible_steps") or []
            sources = data.get("sources") or []
            layers_fired = sorted({_LAYER_STEPS[s["id"]] for s in steps
                                   if s.get("id") in _LAYER_STEPS and s.get("status") == "done"})
            rec = {
                "category": category,
                "question": question,
                "latency_s": round(latency, 1),
                "answer_preview": (data.get("answer") or "")[:240],
                "answer_len": len(data.get("answer") or ""),
                "not_found": data.get("not_found"),
                "confidence": data.get("confidence"),
                "provider_used": data.get("provider_used"),
                "source_count": len(sources),
                "source_hosts": sorted({(s.get("url") or "").split("/")[2] for s in sources if s.get("url")}),
                "citations_present": any("[" in (data.get("answer") or "") for _ in [0]) and bool(sources),
                "layers_fired": layers_fired,
                "origin": _origin(steps, sources),
            }
            out["results"].append(rec)
            print(f"[OK] {category:12s} {latency:5.1f}s origin={rec['origin']:14s} "
                  f"src={rec['source_count']} conf={rec['confidence']} nf={rec['not_found']} "
                  f"layers={'+'.join(layers_fired)}")
    return out


if __name__ == "__main__":
    report = run()
    path = Path("../data/reports/chat_validation.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nChat validation report -> {path}")
