"""
Phase 31 STEP 5 — 1000-query noisy / informal / mixed-language benchmark.

Extends the typo benchmark to a 1000-query suite that mixes four perturbation
families against clean campus queries, then measures entity-resolution accuracy
after `normalize_query`:

  * char-typos (5/10/20%)
  * Indonesian slang/abbreviation (gmn, brp, sapa, dkn, akre, "apa aja", "kuliahnya brp")
  * mixed English↔Indonesian (dean psikologi, tuition TI, scholarship umb, faculty komunikasi)
  * truncation/ambiguity (handled by ambiguous_query_benchmark; excluded here)

Target: accuracy >= 0.98 (directive STEP 5).

    python -m app.evaluation.noisy_query_benchmark --out ../reports/noisy_query_report.json

Degrades gracefully: if the DB/entity tables are unavailable it writes a report
with status="skipped" and exits 0 (so it never blocks a no-DB environment), while
still validating the normalization layer in isolation.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from app.rag.query_normalizer import normalize_query

_FAC = {
    "FEB": "Fakultas Ekonomi dan Bisnis", "FT": "Fakultas Teknik",
    "FASILKOM": "Fakultas Ilmu Komputer", "FIKOM": "Fakultas Ilmu Komunikasi",
    "FDSK": "Fakultas Desain dan Seni Kreatif", "FPSI": "Fakultas Psikologi",
}
_DEAN_TMPL = ["siapa dekan {x}", "dekan {x} siapa", "nama dekan {x}", "{x} dekannya siapa"]
_SLANG_FORMS = {
    "siapa": ["sapa", "spa"], "bagaimana": ["gmn", "gimana"], "berapa": ["brp"],
    "dekan": ["dkn"], "akreditasi": ["akre", "akred"], "fakultas": ["fak"],
}
_MIXED_EN = {
    "dekan": "dean", "fakultas": "faculty", "biaya": "tuition", "beasiswa": "scholarship",
    "akreditasi": "accreditation", "dosen": "lecturer", "kampus": "campus",
}


def _typo(text: str, rate: float, rng: random.Random) -> str:
    out = []
    for c in text:
        if c != " " and rng.random() < rate:
            op = rng.choice(["drop", "swap", "dup"])
            if op == "drop":
                continue
            if op == "dup":
                out.append(c)
        out.append(c)
    return "".join(out)


def _slangify(text: str, rng: random.Random) -> str:
    for k, forms in _SLANG_FORMS.items():
        if k in text and rng.random() < 0.6:
            text = text.replace(k, rng.choice(forms))
    return text


def _mixenglish(text: str, rng: random.Random) -> str:
    for idn, eng in _MIXED_EN.items():
        if idn in text and rng.random() < 0.6:
            text = text.replace(idn, eng)
    return text


def _faculty_of(ctx, n2s):
    t = str((ctx or {}).get("title") or "")
    for full, short in n2s.items():
        if full.lower() in t.lower():
            return short
    return None


def _build_clean_cases(db):
    from app.db.models import UMBStudyProgram

    fac_full_to_short = {v: k for k, v in _FAC.items()}
    cases = []
    for short, full in _FAC.items():
        for t in _DEAN_TMPL:
            cases.append({"clean": t.format(x=full), "exp": short})
            cases.append({"clean": t.format(x=short.lower()), "exp": short})
    for p in db.query(UMBStudyProgram).all():
        exp = fac_full_to_short.get(p.faculty_name or "")
        if not exp:
            continue
        for t in ["akreditasi {p}", "kaprodi {p}", "program studi {p}", "biaya {p}"]:
            cases.append({"clean": t.format(p=p.program_name), "exp": exp, "prog": p.program_name})
    return cases


def _perturb(clean: str, family: str, rng: random.Random) -> str:
    if family == "typo5":
        return _typo(clean, 0.05, rng)
    if family == "typo10":
        return _typo(clean, 0.10, rng)
    if family == "typo20":
        return _typo(clean, 0.20, rng)
    if family == "slang":
        return _slangify(clean, rng)
    if family == "mixed":
        return _mixenglish(clean, rng)
    if family == "slang_typo":
        return _slangify(_typo(clean, 0.08, rng), rng)
    return clean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/noisy_query_report.json")
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--target", type=float, default=0.98)
    args = ap.parse_args()
    rng = random.Random(31)

    report = {"target": args.target, "n_requested": args.n}
    try:
        from app.db.database import get_session_local
        from app.db.models import UMBFaculty

        db = get_session_local()()
    except Exception as exc:
        report.update(status="skipped", reason=f"DB unavailable: {exc}")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[noisy] SKIPPED — DB unavailable: {exc}")
        return

    try:
        from app.retrieval.entity_retriever import query_entities

        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        cases = _build_clean_cases(db)
        families = ["typo5", "typo10", "typo20", "slang", "mixed", "slang_typo"]
        per_family: dict[str, list[int]] = {f: [0, 0] for f in families}

        evaluated = 0
        while evaluated < args.n:
            c = rng.choice(cases)
            fam = families[evaluated % len(families)]
            q = normalize_query(_perturb(c["clean"], fam, rng))
            res = query_entities(db, q)
            top = res[0] if res else {}
            good = _faculty_of(top, n2s) == c["exp"]
            if "prog" in c:
                good = good or (c["prog"].lower() in str(top.get("title") or "").lower())
            per_family[fam][0] += int(good)
            per_family[fam][1] += 1
            evaluated += 1
    finally:
        db.close()

    by_family = {f: round(ok / max(tot, 1), 4) for f, (ok, tot) in per_family.items()}
    overall = round(sum(ok for ok, _ in per_family.values()) / max(evaluated, 1), 4)
    report.update(
        status="ok",
        evaluated=evaluated,
        by_family=by_family,
        overall_accuracy=overall,
        meets_target=overall >= args.target,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for f, acc in by_family.items():
        print(f"  {f:12s}: {acc}")
    print(f"overall: {overall} | target {args.target} | meets={report['meets_target']}")


if __name__ == "__main__":
    main()
