"""Phase 5 analysis: before/after comparison, failure analysis, top-20 reports,
latency profile, grounding summary. Reads benchmark JSONs and emits a consolidated
validation_analysis.json + prints a readable summary.

Usage:
  python -m app.evaluation.analyze_validation \
      --before ../data/reports/benchmark_report.json \
      --after  ../data/reports/benchmark_agent_full.json \
      --out    ../data/reports/validation_analysis.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def _load(path):
    return json.load(open(path, encoding="utf-8"))


def _pctl(values, p):
    if not values:
        return None
    s = sorted(values)
    return round(s[max(0, int(p * len(s)) - 1)], 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--out", default="../data/reports/validation_analysis.json")
    args = ap.parse_args()

    before = _load(args.before)
    after = _load(args.after)
    rec = after["results"]
    answer_bearing = [r for r in rec if not r["is_control"]]
    controls = [r for r in rec if r["is_control"]]

    # --- Task 4: before/after category comparison ---
    cats = sorted(set(before["by_category"]) | set(after["by_category"]))
    comparison = []
    for c in cats:
        b = before["by_category"].get(c, {})
        a = after["by_category"].get(c, {})
        if b.get("is_control") or a.get("is_control"):
            continue
        ba, aa = b.get("answerability"), a.get("answerability")
        comparison.append({
            "category": c,
            "answerability_before": ba,
            "answerability_after": aa,
            "delta": round((aa or 0) - (ba or 0), 3) if (aa is not None and ba is not None) else None,
            "citation_fail_before": b.get("citation_failure_rate"),
            "citation_fail_after": a.get("citation_failure_rate"),
        })
    comparison.sort(key=lambda x: (x["delta"] if x["delta"] is not None else 0))

    overall_cmp = {
        "answerability": {"before": before["overall"]["answerability"], "after": after["overall"]["answerability"]},
        "retrieval_accuracy": {"before": before["overall"]["retrieval_accuracy"], "after": after["overall"]["retrieval_accuracy"]},
        "coverage": {"before": before["overall"]["coverage"], "after": after["overall"]["coverage"]},
        "citation_failure_rate": {"before": before["overall"]["citation_failure_rate"], "after": after["overall"]["citation_failure_rate"]},
        "control_abstention_correct": {"before": before["overall"].get("control_abstention_correct"), "after": after["overall"].get("control_abstention_correct")},
    }

    # --- Task 5/6: failure analysis + top-20 reports ---
    retrieval_failures = [
        {"id": r["id"], "category": r["category"], "qtype": r["qtype"], "question": r["question"],
         "retrieved_hosts": r["retrieved_hosts"], "top_source_layer": r.get("top_source_layer")}
        for r in answer_bearing if not r["answerable"]
    ]
    # retrieval miss = a labelled target existed but was NOT hit
    retrieval_misses = [
        {"id": r["id"], "category": r["category"], "question": r["question"], "target_rank": r.get("target_rank"),
         "retrieved_hosts": r["retrieved_hosts"]}
        for r in answer_bearing if r.get("target_hit") is False
    ]
    # citation failures = archive/forbidden host at rank 1
    citation_failures = [
        {"id": r["id"], "category": r["category"], "question": r["question"],
         "top_host": (r["retrieved_hosts"][0] if r["retrieved_hosts"] else None)}
        for r in rec if r["noisy_at_1"]
    ]
    # control leaks = a control that surfaced sources (potential hallucination risk)
    control_leaks = [
        {"id": r["id"], "category": r["category"], "question": r["question"], "hosts": r["retrieved_hosts"]}
        for r in controls if r["sources_found"]
    ]

    # missing knowledge domains = categories below answerability target, ranked
    missing_domains = sorted(
        [{"category": c["category"], "answerability_after": c["answerability_after"], "delta_vs_before": c["delta"]}
         for c in comparison if (c["answerability_after"] or 0) < 0.90],
        key=lambda x: x["answerability_after"] or 0,
    )

    # --- Task 7: latency profile (overall + per layer-origin + per category) ---
    lat_all = [r["latency_ms"] for r in rec]
    by_layer_latency = {}
    for layer in ("FAQ", "Entity", "GraphRAG", "Vector"):
        vals = [r["latency_ms"] for r in rec if r.get("top_source_layer") == layer]
        if vals:
            by_layer_latency[layer] = {"n": len(vals), "median": round(statistics.median(vals), 1),
                                       "p95": _pctl(vals, 0.95), "p99": _pctl(vals, 0.99)}
    latency_profile = {
        "overall_ms": {"median": round(statistics.median(lat_all), 1), "p95": _pctl(lat_all, 0.95), "p99": _pctl(lat_all, 0.99),
                       "max": round(max(lat_all), 1)},
        "by_top_layer_ms": by_layer_latency,
    }

    # --- layer distribution / structured share ---
    layer_dist = after["overall"].get("answer_source_layers", {})
    structured_share = after["overall"].get("structured_layer_share")

    # --- Task 8: grounding (generation tier if present) ---
    grounding = {"note": "retrieval-tier run; generation groundedness measured separately if --with-generation used"}
    if after["overall"].get("generation"):
        grounding = after["overall"]["generation"]

    out = {
        "before_file": args.before,
        "after_file": args.after,
        "overall_comparison": overall_cmp,
        "answer_source_layers": layer_dist,
        "structured_layer_share": structured_share,
        "category_comparison": comparison,
        "missing_knowledge_domains": missing_domains,
        "latency_profile": latency_profile,
        "grounding": grounding,
        "counts": {
            "retrieval_failures": len(retrieval_failures),
            "retrieval_misses": len(retrieval_misses),
            "citation_failures": len(citation_failures),
            "control_leaks": len(control_leaks),
        },
        "top20_retrieval_failures": retrieval_failures[:20],
        "top20_retrieval_misses": retrieval_misses[:20],
        "top20_citation_failures": citation_failures[:20],
        "control_leaks": control_leaks[:20],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- print summary ----
    print("=== BEFORE vs AFTER (overall) ===")
    for k, v in overall_cmp.items():
        print(f"  {k:26s} before={v['before']}  after={v['after']}")
    print(f"\n  answer source layers (after): {layer_dist}  structured_share={structured_share}")
    print("\n=== CATEGORY COMPARISON (sorted by delta) ===")
    print(f"  {'category':22s} {'before':>7} {'after':>7} {'delta':>7}")
    for c in comparison:
        print(f"  {c['category']:22s} {str(c['answerability_before']):>7} {str(c['answerability_after']):>7} {str(c['delta']):>7}")
    print("\n=== MISSING KNOWLEDGE DOMAINS (after < 0.90) ===")
    for m in missing_domains:
        print(f"  {m['category']:22s} {m['answerability_after']}  (delta {m['delta_vs_before']})")
    print("\n=== LATENCY PROFILE (ms) ===")
    print(f"  overall: {latency_profile['overall_ms']}")
    for layer, v in by_layer_latency.items():
        print(f"  {layer:10s}: {v}")
    print("\n=== FAILURE COUNTS ===")
    for k, v in out["counts"].items():
        print(f"  {k}: {v}")
    print(f"\nAnalysis -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
