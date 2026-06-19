"""Phase 15 P1 — faculty / program disambiguation + leakage benchmark.

For every dekan / wakil dekan / kaprodi / akreditasi / faculty query we assert
the structured entity layer resolves to the CORRECT faculty (or the correct
program and its real faculty) and that NO other faculty leaks into the top slot.
Specifically a FEB question must never surface FASILKOM, a program question must
never surface an unrelated faculty, etc.

    python -m app.evaluation.faculty_disambiguation_benchmark \
        --out ../reports/faculty_disambiguation_report.json

NB: UMB has 7 faculties — FEB, FT, FASILKOM, FIKOM, FDSK, FPSI, Pascasarjana.
"FDIK" (in the Phase-15 brief) is not a real UMB faculty (likely a typo for
FDSK) and is reported as absent rather than fabricated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.retrieval.entity_retriever import query_entities

# Aliases the entity layer recognises, per faculty short name.
_FACULTY_QUERY_ALIASES = {
    "FEB": ["FEB", "Fakultas Ekonomi dan Bisnis"],
    "FT": ["FT", "Fakultas Teknik"],
    "FASILKOM": ["FASILKOM", "Fakultas Ilmu Komputer"],
    "FIKOM": ["FIKOM", "Fakultas Ilmu Komunikasi"],
    "FDSK": ["FDSK", "Fakultas Desain dan Seni Kreatif"],
    "FPSI": ["FPSI", "Fakultas Psikologi"],
    "PASCA": ["Pascasarjana"],
}
_BRIEF_FACULTIES = ["FEB", "FASILKOM", "FIKOM", "FT", "FDSK", "FPSI", "FDIK"]

_DEAN_TMPL = [
    "Siapa dekan {x} saat ini?", "Dekan {x}", "Wakil dekan {x}",
    "Nama dekan {x}", "Siapa pimpinan {x}?",
]
_FAC_ACC_TMPL = ["Akreditasi {x}", "Akreditasi fakultas {x}", "Status akreditasi {x}"]
# Program keyword -> (canonical program name substring, owning faculty short name).
_PROGRAM_FACULTY = {
    "Sistem Informasi": "FASILKOM", "Teknik Informatika": "FASILKOM",
    "Manajemen": "FEB", "Akuntansi": "FEB",
    "Teknik Elektro": "FT", "Teknik Mesin": "FT", "Teknik Sipil": "FT", "Teknik Industri": "FT", "Arsitektur": "FT",
    "Desain Komunikasi Visual": "FDSK",
    "Penyiaran": "FIKOM", "Periklanan": "FIKOM", "Hubungan Masyarakat": "FIKOM",
}
_PROG_TMPL = ["Akreditasi {x}", "Kaprodi {x}", "Ketua program studi {x}", "Siapa kaprodi {x}?"]


def _faculty_of_context(ctx: dict, fac_name_to_short: dict[str, str]) -> str | None:
    """Return the faculty short-name a context belongs to, or None."""
    et = ctx.get("entity_type")
    title = str(ctx.get("title") or "")
    if et == "faculty":
        for full, short in fac_name_to_short.items():
            if full.lower() in title.lower():
                return short
    if et == "study_program":
        # program title is "<program> — <faculty full name>"
        for full, short in fac_name_to_short.items():
            if full.lower() in title.lower():
                return short
    return None


def build_and_run(db) -> dict:
    faculties = {f.name_short: f for f in db.query(UMBFaculty).all() if f.name_short}
    fac_name_to_short = {f.name: f.name_short for f in faculties.values()}

    cases: list[dict] = []
    for short, aliases in _FACULTY_QUERY_ALIASES.items():
        for alias in aliases:
            for t in _DEAN_TMPL:
                cases.append({"q": t.format(x=alias), "expect_short": short, "kind": "dean"})
            for t in _FAC_ACC_TMPL:
                cases.append({"q": t.format(x=alias), "expect_short": short, "kind": "faculty_acc"})
    for prog, short in _PROGRAM_FACULTY.items():
        for t in _PROG_TMPL:
            cases.append({"q": t.format(x=prog), "expect_short": short, "kind": "program",
                          "expect_program": prog})

    resolved = 0
    leakage = 0
    fasilkom_leak = 0
    failures: list[dict] = []
    for c in cases:
        ctxs = query_entities(db, c["q"])
        top = ctxs[0] if ctxs else {}
        top_short = _faculty_of_context(top, fac_name_to_short)
        # program cases: also require the program name in the title.
        prog_ok = True
        if c["kind"] == "program":
            prog_ok = c["expect_program"].lower() in str(top.get("title") or "").lower()
        ok = (top_short == c["expect_short"]) and prog_ok
        resolved += ok
        # leakage = any returned context belongs to a DIFFERENT faculty in the top-3.
        leaked_shorts = {
            _faculty_of_context(x, fac_name_to_short) for x in ctxs[:3]
        } - {None, c["expect_short"]}
        if leaked_shorts:
            leakage += 1
            if "FASILKOM" in leaked_shorts and c["expect_short"] != "FASILKOM":
                fasilkom_leak += 1
        if not ok and len(failures) < 40:
            failures.append({"q": c["q"], "expect": c["expect_short"], "kind": c["kind"],
                             "got_short": top_short, "got_title": str(top.get("title") or "")[:54]})

    return {
        "total_cases": len(cases),
        "faculty_resolution_accuracy": round(resolved / max(len(cases), 1), 4),
        "faculty_leakage_count": leakage,
        "fasilkom_leakage_count": fasilkom_leak,
        "faculties_present": sorted(faculties.keys()),
        "brief_faculties_absent": [f for f in _BRIEF_FACULTIES if f not in faculties],
        "failures": failures,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/faculty_disambiguation_report.json")
    args = ap.parse_args()
    db = get_session_local()()
    try:
        report = build_and_run(db)
    finally:
        db.close()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases={report['total_cases']} "
          f"faculty_resolution={report['faculty_resolution_accuracy']} "
          f"leakage={report['faculty_leakage_count']} fasilkom_leak={report['fasilkom_leakage_count']}")
    print("absent from KB (brief):", report["brief_faculties_absent"])
    for f in report["failures"][:12]:
        print("  FAIL", f)


if __name__ == "__main__":
    main()
