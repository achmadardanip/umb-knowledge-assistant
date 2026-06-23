"""Deterministic adversarial-scenario generator for robustness testing.

Turns base questions into tagged perturbations (typo / incomplete / mixed_lang /
ambiguous) for the Promptfoo monitoring eval. Pure, seeded functions => reproducible.
Output CSV columns: query, intent, perturbation_type, base_id.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_GOLDEN = _ROOT / "data" / "golden_dataset" / "golden_dataset.jsonl"
_OUT = _ROOT / "evaluation" / "promptfoo" / "adversarial_scenarios.csv"
_SEED = 20260622

PERTURBATION_TYPES = ("typo", "incomplete", "mixed_lang", "ambiguous")

_ID_TO_EN = {
    "siapa": "who", "berapa": "how much", "biaya": "cost", "fakultas": "faculty",
    "jadwal": "schedule", "mahasiswa": "student", "bagaimana": "how", "kapan": "when",
    "dimana": "where", "apa": "what", "dosen": "lecturer", "syarat": "requirements",
}


def make_typo(question: str, rng: random.Random) -> str:
    """Apply a light character-level typo to up to two words."""
    words = question.split()
    idxs = [i for i, w in enumerate(words) if len(w.strip("?.,!")) >= 4]
    rng.shuffle(idxs)
    for i in idxs[:2]:
        w = words[i]
        j = rng.randrange(len(w) - 1)
        op = rng.choice(("swap", "drop", "dup"))
        if op == "swap":
            w = w[:j] + w[j + 1] + w[j] + w[j + 2:]
        elif op == "drop":
            w = w[:j] + w[j + 1:]
        else:  # dup
            w = w[:j] + w[j] + w[j:]
        words[i] = w
    out = " ".join(words)
    if out == question and idxs:  # guarantee a visible change (e.g. swap hit doubled chars)
        i = idxs[0]
        words[i] = words[i][1:] or words[i]
        out = " ".join(words)
    return out


def make_incomplete(question: str, rng: random.Random) -> str | None:
    """Truncate to the first k words (2 <= k < len). None if too short."""
    words = question.split()
    if len(words) < 3:
        return None
    k = rng.randrange(2, len(words))
    return " ".join(words[:k])


def make_mixed_lang(question: str, rng: random.Random) -> str | None:
    """Code-switch some Indonesian tokens to English. None if none replaceable."""
    words = question.split()
    known = [i for i, w in enumerate(words) if w.lower().strip("?.,!") in _ID_TO_EN]
    if not known:
        return None
    rng.shuffle(known)
    # always replace at least one known token; additional ones at 50% chance
    to_replace = {known[0]} | {i for i in known[1:] if rng.random() < 0.5}
    out = []
    for i, w in enumerate(words):
        out.append(_ID_TO_EN[w.lower().strip("?.,!")] if i in to_replace else w)
    return " ".join(out)


def make_ambiguous(question: str, rng: random.Random) -> str | None:
    """Strip specific named entities (proper nouns) -> a vaguer question."""
    words = question.split()
    if not words:
        return None
    kept, removed = [words[0]], False
    for w in words[1:]:
        core = w.strip("?.,!")
        if core and (core[:1].isupper() or core.isupper()):
            removed = True
            continue
        kept.append(w)
    if not removed:
        return None
    out = " ".join(kept).rstrip("?.,! ")
    return (out + "?") if out else None


_MAKERS = {
    "typo": make_typo, "incomplete": make_incomplete,
    "mixed_lang": make_mixed_lang, "ambiguous": make_ambiguous,
}


def perturb(question: str, base_id: str, intent: str, seed: int,
            types=PERTURBATION_TYPES) -> list[dict]:
    """Generate tagged perturbation rows for one base question (no-ops dropped)."""
    rows = []
    for t in types:
        rng = random.Random(f"{seed}:{base_id}:{t}")
        v = _MAKERS[t](question, rng)
        if v and v.strip() and v != question:
            rows.append({"query": v, "intent": intent, "perturbation_type": t, "base_id": base_id})
    return rows


def load_golden(path: Path = _GOLDEN) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _stratified_base(rows: list[dict], n: int, seed: int) -> list[dict]:
    pool = [r for r in rows if r.get("answerable") and not r.get("synthetic")]
    by_intent: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_intent[r.get("intent") or "general"].append(r)
    rng = random.Random(seed)
    for items in by_intent.values():
        rng.shuffle(items)
    intents = sorted(by_intent)
    selected, idx = [], 0
    while len(selected) < n and any(by_intent.values()):
        bucket = by_intent[intents[idx % len(intents)]]
        if bucket:
            selected.append(bucket.pop())
        idx += 1
        if idx > n * 100:
            break
    return selected[:n]


def build(base_n: int = 20, types=PERTURBATION_TYPES, seed: int = _SEED,
          golden: Path = _GOLDEN) -> list[dict]:
    bases = _stratified_base(load_golden(golden), base_n, seed)
    out = []
    for r in bases:
        out.extend(perturb(r["question"], base_id=r["id"],
                           intent=r.get("intent") or "general", seed=seed, types=types))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=int, default=20)
    ap.add_argument("--types", default=",".join(PERTURBATION_TYPES))
    ap.add_argument("--seed", type=int, default=_SEED)
    ap.add_argument("--out", default=str(_OUT))
    args = ap.parse_args()
    types = tuple(t.strip() for t in args.types.split(",") if t.strip())
    rows = build(args.base, types, args.seed)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["query", "intent", "perturbation_type", "base_id"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} adversarial rows -> {args.out}")


if __name__ == "__main__":
    main()
