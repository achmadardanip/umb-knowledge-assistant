"""Phase 29.1 — real-user random campus query benchmark.

Generates 1000 realistic queries (informal Indonesian, slang, abbreviations, typos,
conversational follow-ups) across campus categories and measures accuracy through
the production path: normalize_query -> (session memory for follow-ups) ->
query_entities / official-source check.

    python -m app.evaluation.campus_random_query_benchmark --out ../reports/campus_random_query_report.json
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from pathlib import Path

from app.chat.session_memory import SessionMemory
from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.rag.followup_resolution import enrich_query
from app.rag.query_normalizer import normalize_query
from app.retrieval.entity_retriever import query_entities

_FAC = {"FEB": "Fakultas Ekonomi dan Bisnis", "FT": "Fakultas Teknik",
        "FASILKOM": "Fakultas Ilmu Komputer", "FIKOM": "Fakultas Ilmu Komunikasi",
        "FDSK": "Fakultas Desain dan Seni Kreatif", "FPSI": "Fakultas Psikologi"}
_DEAN = ["siapa dekan {x}", "dekan {x} siapa skrg", "dekan {x}", "nama dekan {x} sekarang"]
_PROG = ["akreditasi {p}", "akreditsi {p}", "kaprodi {p}", "kaprodi {p} siapa ya", "program studi {p}"]
_SLANG = {"siapa": "sapa", "sekarang": "skrg", "bagaimana": "gmn", "berapa": "brp",
          "teknik informatika": "ti", "sistem informasi": "si"}


def _typo(s, rate, rng):
    out = []
    for c in s:
        if c != " " and rng.random() < rate:
            if rng.random() < 0.5:
                continue  # drop
            out.append(c)  # dup
        out.append(c)
    return "".join(out)


def _noise(s, rng):
    r = rng.random()
    if r < 0.33:
        return s  # clean
    if r < 0.66:
        for k, v in _SLANG.items():
            if k in s and rng.random() < 0.6:
                s = s.replace(k, v)
        return s
    return _typo(s, rng.choice([0.05, 0.10, 0.20]), rng)


def _faculty_of(ctx, n2s):
    t = str((ctx or {}).get("title") or "")
    for full, short in n2s.items():
        if full.lower() in t.lower():
            return short
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/campus_random_query_report.json")
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()
    rng = random.Random(7)
    db = get_session_local()()
    try:
        n2s = {f.name: f.name_short for f in db.query(UMBFaculty).all() if f.name_short}
        progs = {p.program_name: (p.faculty_name or "") for p in db.query(UMBStudyProgram).all()}
        fac_full_to_short = {v: k for k, v in _FAC.items()}

        cat_total, cat_ok = {}, {}
        followups_total = followups_ok = 0
        n = 0
        while n < args.n:
            kind = rng.choice(["dean", "program", "followup"])
            if kind == "dean":
                short = rng.choice(list(_FAC))
                tgt = rng.choice([_FAC[short], short.lower()])
                q = _noise(rng.choice(_DEAN).format(x=tgt), rng)
                res = query_entities(db, normalize_query(q))
                ok = _faculty_of(res[0] if res else {}, n2s) == short
            elif kind == "program":
                pname = rng.choice(list(progs))
                exp = fac_full_to_short.get(progs[pname])
                if not exp:
                    continue
                q = _noise(rng.choice(_PROG).format(p=pname), rng)
                res = query_entities(db, normalize_query(q))
                top = res[0] if res else {}
                ok = _faculty_of(top, n2s) == exp or pname.lower() in str(top.get("title") or "").lower()
            else:  # follow-up conversation
                mem = SessionMemory(); sid = str(uuid.uuid4())
                short = rng.choice(list(_FAC))
                est = f"ceritakan tentang {_FAC[short]}"
                mem.remember(sid, query=normalize_query(est), contexts=query_entities(db, normalize_query(est)), intent="faculty")
                fu = _noise(rng.choice(["siapa dekannya", "akreditasinya gmn", "beliau menjabat sejak kapan"]), rng)
                res = query_entities(db, enrich_query(normalize_query(fu), mem.recall(sid)))
                ok = _faculty_of(res[0] if res else {}, n2s) == short
                followups_total += 1; followups_ok += ok
            cat_total[kind] = cat_total.get(kind, 0) + 1
            cat_ok[kind] = cat_ok.get(kind, 0) + (1 if ok else 0)
            n += 1

        per_cat = {k: round(cat_ok[k] / cat_total[k], 4) for k in cat_total}
        overall = round(sum(cat_ok.values()) / max(sum(cat_total.values()), 1), 4)
        report = {
            "total_queries": n,
            "overall_accuracy": overall,
            "per_category": per_cat,
            "category_counts": cat_total,
            "followup_accuracy": round(followups_ok / max(followups_total, 1), 4),
            "target": 0.95,
            "meets_target": overall >= 0.95,
        }
    finally:
        db.close()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"overall={overall} per_category={per_cat} (target 0.95, meets={report['meets_target']})")


if __name__ == "__main__":
    main()
