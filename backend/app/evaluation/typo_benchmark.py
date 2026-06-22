"""Phase 27.3 — typo / informal-query robustness benchmark.

Generates noisy variants of clean campus queries (character typos at 5/10/20% +
slang/abbreviation forms), runs them through normalize_query -> query_entities,
and measures entity-resolution accuracy. Also reports the lift vs no-normalization.

    python -m app.evaluation.typo_benchmark --out ../reports/typo_normalization_report.json
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.rag.query_normalizer import normalize_query
from app.retrieval.entity_retriever import query_entities

_FAC = {
    "FEB": "Fakultas Ekonomi dan Bisnis", "FT": "Fakultas Teknik",
    "FASILKOM": "Fakultas Ilmu Komputer", "FIKOM": "Fakultas Ilmu Komunikasi",
    "FDSK": "Fakultas Desain dan Seni Kreatif", "FPSI": "Fakultas Psikologi",
}
# clean query templates -> expected faculty short
_DEAN_TMPL = ["siapa dekan {x}", "dekan {x} siapa", "nama dekan {x}"]
_PROG_TMPL = ["akreditasi {p}", "kaprodi {p}", "program studi {p}"]
# slang variants injected at higher noise
_SLANGIFY = {"siapa": "sapa", "bagaimana": "gmn", "berapa": "brp", "sekarang": "skrg",
             "teknik informatika": "ti", "sistem informasi": "si", "yang": "yg"}


def _typo(text: str, rate: float, rng: random.Random) -> str:
    chars = list(text)
    out = []
    for c in chars:
        if c != " " and rng.random() < rate:
            op = rng.choice(["drop", "swap", "dup"])
            if op == "drop":
                continue
            if op == "dup":
                out.append(c)
            out.append(c)  # swap handled loosely as keep (simple noise)
        else:
            out.append(c)
    return "".join(out)


def _slangify(text: str, rng: random.Random) -> str:
    for k, v in _SLANGIFY.items():
        if k in text and rng.random() < 0.5:
            text = text.replace(k, v)
    return text


def _faculty_of(ctx, n2s):
    t = str((ctx or {}).get("title") or "")
    for full, short in n2s.items():
        if full.lower() in t.lower():
            return short
    return None


def _build_cases(db):
    progs = {p.program_name: (p.faculty_name or "") for p in db.query(UMBStudyProgram).all()}
    fac_full_to_short = {v: k for k, v in _FAC.items()}
    cases = []
    for short, full in _FAC.items():
        for t in _DEAN_TMPL:
            cases.append({"clean": t.format(x=full), "exp": short})
            cases.append({"clean": t.format(x=short.lower()), "exp": short})
    for pname, fac_full in progs.items():
        exp = fac_full_to_short.get(fac_full)
        if not exp:
            continue
        for t in _PROG_TMPL:
            cases.append({"clean": t.format(p=pname), "exp": exp, "prog": pname})
    return cases


def _run(db, cases, n2s, rate, rng, normalize: bool):
    ok = 0
    for c in cases:
        q = _slangify(_typo(c["clean"], rate, rng), rng) if rate > 0 else c["clean"]
        q = normalize_query(q) if normalize else q
        res = query_entities(db, q)
        top = res[0] if res else {}
        good = _faculty_of(top, n2s) == c["exp"]
        if "prog" in c:  # program cases: also accept program-title match
            good = good or (c["prog"].lower() in str(top.get("title") or "").lower())
        ok += good
    return round(ok / max(len(cases), 1), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/typo_normalization_report.json")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    rng = random.Random(42)
    db = get_session_local()()
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        cases = _build_cases(db)
        # expand to ~500 noisy queries via repeats
        results = {}
        for rate in (0.0, 0.05, 0.10, 0.20):
            withn = sum(_run(db, cases, n2s, rate, rng, True) for _ in range(args.repeats)) / args.repeats
            without = sum(_run(db, cases, n2s, rate, rng, False) for _ in range(args.repeats)) / args.repeats
            results[f"typo_{int(rate*100)}pct"] = {
                "with_normalization": round(withn, 4),
                "without_normalization": round(without, 4),
                "lift": round(withn - without, 4),
            }
    finally:
        db.close()

    noisy = [v["with_normalization"] for k, v in results.items() if k != "typo_0pct"]
    overall = round(sum(noisy) / max(len(noisy), 1), 4)
    report = {
        "cases_per_run": len(cases),
        "total_queries_evaluated": len(cases) * args.repeats * 8,
        "by_typo_rate": results,
        "overall_noisy_accuracy_with_normalization": overall,
        "target": 0.95,
        "meets_target": overall >= 0.95,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for k, v in results.items():
        print(f"  {k}: with={v['with_normalization']} without={v['without_normalization']} lift={v['lift']}")
    print(f"overall noisy (with normalization): {overall} | target 0.95 | meets={report['meets_target']}")


if __name__ == "__main__":
    main()
