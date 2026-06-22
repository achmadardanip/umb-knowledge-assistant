"""Deterministic stratified sampler over data/golden_dataset.jsonl for the RAG eval.

Selects authentic, answerable questions spread evenly across intents with a fixed seed,
and writes them to evaluation/promptfoo/datasets/rag_golden.json. Reproducible:
same input + seed => same slice.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_GOLDEN = _ROOT / "data" / "golden_dataset" / "golden_dataset.jsonl"
_OUT = _ROOT / "evaluation" / "promptfoo" / "datasets" / "rag_golden.json"
_SEED = 20260622


def load_golden(path: Path = _GOLDEN) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def stratified_sample(rows: list[dict], size: int, seed: int = _SEED) -> list[dict]:
    pool = [r for r in rows if r.get("answerable") and not r.get("synthetic")]
    by_intent: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_intent[r.get("intent") or "general"].append(r)
    rng = random.Random(seed)
    for items in by_intent.values():
        rng.shuffle(items)
    intents = sorted(by_intent)
    selected: list[dict] = []
    idx = 0
    while len(selected) < size and any(by_intent.values()):
        bucket = by_intent[intents[idx % len(intents)]]
        if bucket:
            r = bucket.pop()
            selected.append({"id": r["id"], "question": r["question"], "intent": r.get("intent") or "general"})
        idx += 1
        if idx > size * 100:
            break
    return selected[:size]


def build(size: int = 40) -> list[dict]:
    return stratified_sample(load_golden(), size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=40)
    ap.add_argument("--out", default=str(_OUT))
    args = ap.parse_args()
    rows = build(args.size)
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} questions -> {args.out}")


if __name__ == "__main__":
    main()
