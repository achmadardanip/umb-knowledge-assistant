"""Phase 14 P3 — Entity resolution benchmark suite.

Generates a large, deterministic set of dean / kaprodi / accreditation / faculty /
program queries from the *real* umb_* records and measures whether the structured
entity layer (``query_entities``) resolves each to the correct entity TYPE (and,
where unambiguous, the correct named entity).

Usage:
    python -m app.evaluation.entity_benchmark \
        --out-dataset ../reports/entity_benchmark_v1.json \
        --out-report  ../reports/entity_benchmark_report.json

Requires LOCAL_POSTGRES_MODE=true + LOCAL_POSTGRES_URL pointing at the KB.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.retrieval.entity_retriever import _PROGRAM_NAME_MAP, query_entities

# Faculty abbreviation/keyword aliases that the entity layer recognises and that
# are NOT also study-program keywords (so an accreditation query stays faculty).
_FACULTY_ALIASES = {
    "FEB": ["FEB", "Fakultas Ekonomi dan Bisnis", "fakultas ekonomi"],
    "FT": ["FT", "Fakultas Teknik", "fakultas teknik"],
    "FASILKOM": ["FASILKOM", "Fakultas Ilmu Komputer", "fakultas ilmu komputer"],
    "FIKOM": ["FIKOM", "Fakultas Ilmu Komunikasi", "fakultas ilmu komunikasi"],
    "FDSK": ["FDSK", "Fakultas Desain dan Seni Kreatif", "fakultas desain"],
    "FPSI": ["FPSI", "Fakultas Psikologi", "fakultas psikologi"],
    "PASCA": ["Pascasarjana", "pascasarjana"],
}
# Distinctive substring used to confirm the correct faculty was returned.
_FACULTY_NAME_HINT = {
    "FEB": "Ekonomi",
    "FT": "Fakultas Teknik",
    "FASILKOM": "Ilmu Komputer",
    "FIKOM": "Ilmu Komunikasi",
    "FDSK": "Desain",
    "FPSI": "Psikologi",
    "PASCA": "Pascasarjana",
}

_DEAN_TEMPLATES = [
    "Siapa dekan {x}?",
    "Dekan {x} siapa?",
    "Nama dekan {x}",
    "{x} dekannya siapa",
    "Pimpinan {x} sekarang",
    "Siapa pimpinan fakultas {x}?",
    "dekan {x}",
    "Sebutkan dekan {x}",
]
_FACULTY_TEMPLATES = [
    "Tentang {x}",
    "Profil {x}",
    "{x}",
    "Apa itu {x}?",
    "Jelaskan tentang {x}",
    "Detail {x}",
    "Sejarah {x}",
    "Visi misi {x}",
]
_KAPRODI_TEMPLATES = [
    "Siapa kaprodi {x}?",
    "Ketua program studi {x}",
    "Kaprodi {x} siapa?",
    "Nama kaprodi {x}",
    "Ketua prodi {x}",
    "kaprodi {x}",
    "Siapa ketua program studi {x}?",
    "Kepala program studi {x}",
]
_PROGRAM_TEMPLATES = [
    "Program studi {x}",
    "Prodi {x}",
    "Tentang program {x}",
    "Jurusan {x}",
    "Profil prodi {x}",
    "program studi {x}",
    "Detail program studi {x}",
    "Jelaskan prodi {x}",
]
_ACC_PROGRAM_TEMPLATES = [
    "Akreditasi {x}",
    "Akreditasi program studi {x}",
    "Akreditasi prodi {x}",
    "Status akreditasi {x}",
    "Peringkat akreditasi {x}",
    "akreditasi jurusan {x}",
]
_ACC_FACULTY_TEMPLATES = [
    "Akreditasi {x}",
    "Akreditasi fakultas {x}",
    "Status akreditasi {x}",
    "Peringkat akreditasi {x}",
]


def build_dataset(db) -> list[dict]:
    rows: list[dict] = []
    faculties = {f.name_short: f for f in db.query(UMBFaculty).all() if f.name_short}
    programs = db.query(UMBStudyProgram).all()
    prog_keywords = sorted(set(_PROGRAM_NAME_MAP.keys()))

    def add(cat, query, expected_type, hint=None):
        rows.append({
            "id": f"{cat}-{len(rows):04d}",
            "category": cat,
            "query": query,
            "expected_type": expected_type,
            "expected_name_contains": hint,
        })

    # 1) Dean queries (faculty) + 4) faculty info queries — per faculty alias.
    for abbr, aliases in _FACULTY_ALIASES.items():
        hint = _FACULTY_NAME_HINT[abbr]
        for alias in aliases:
            for tmpl in _DEAN_TEMPLATES:
                add("dean", tmpl.format(x=alias), "faculty", hint)
            for tmpl in _FACULTY_TEMPLATES:
                add("faculty", tmpl.format(x=alias), "faculty", hint)
        # Faculty-level accreditation (no program keyword in the alias).
        for tmpl in _ACC_FACULTY_TEMPLATES:
            add("accreditation", tmpl.format(x=abbr), "faculty", hint)

    # 2) Kaprodi (program) + 5) program info + 3) program accreditation — per
    # mappable program keyword (these are the ones the program lookup resolves).
    for kw in prog_keywords:
        canonical = _PROGRAM_NAME_MAP[kw]
        for tmpl in _KAPRODI_TEMPLATES:
            add("kaprodi", tmpl.format(x=canonical), "study_program", canonical)
        for tmpl in _PROGRAM_TEMPLATES:
            add("program", tmpl.format(x=canonical), "study_program", canonical)
        for tmpl in _ACC_PROGRAM_TEMPLATES:
            add("accreditation", tmpl.format(x=canonical), "study_program", canonical)

    return rows


def evaluate(db, dataset: list[dict]) -> dict:
    from collections import defaultdict

    cat_total: dict[str, int] = defaultdict(int)
    cat_type_ok: dict[str, int] = defaultdict(int)
    cat_name_ok: dict[str, int] = defaultdict(int)
    failures: list[dict] = []

    for item in dataset:
        cat = item["category"]
        cat_total[cat] += 1
        results = query_entities(db, item["query"])
        top = results[0] if results else {}
        et = top.get("entity_type")
        title = str(top.get("title") or "")
        type_ok = et == item["expected_type"]
        hint = item.get("expected_name_contains")
        name_ok = type_ok and (not hint or hint.lower() in title.lower())
        if type_ok:
            cat_type_ok[cat] += 1
        if name_ok:
            cat_name_ok[cat] += 1
        if not name_ok and len(failures) < 60:
            failures.append({
                "query": item["query"], "category": cat,
                "expected_type": item["expected_type"], "expected_name": hint,
                "got_type": et, "got_title": title[:60],
            })

    per_category = {}
    for cat in sorted(cat_total):
        tot = cat_total[cat]
        per_category[cat] = {
            "total": tot,
            "type_accuracy": round(cat_type_ok[cat] / tot, 4),
            "name_accuracy": round(cat_name_ok[cat] / tot, 4),
        }
    total = sum(cat_total.values())
    return {
        "total_queries": total,
        "overall_type_accuracy": round(sum(cat_type_ok.values()) / total, 4),
        "overall_name_accuracy": round(sum(cat_name_ok.values()) / total, 4),
        "per_category": per_category,
        "failures_sample": failures,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dataset", default="../reports/entity_benchmark_v1.json")
    ap.add_argument("--out-report", default="../reports/entity_benchmark_report.json")
    args = ap.parse_args()

    db = get_session_local()()
    try:
        dataset = build_dataset(db)
        report = evaluate(db, dataset)
    finally:
        db.close()

    Path(args.out_dataset).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_dataset).write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.out_report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"dataset: {len(dataset)} queries -> {args.out_dataset}")
    print(f"overall_type_accuracy: {report['overall_type_accuracy']}  "
          f"overall_name_accuracy: {report['overall_name_accuracy']}")
    for cat, m in report["per_category"].items():
        print(f"  {cat:14s} n={m['total']:>3}  type={m['type_accuracy']}  name={m['name_accuracy']}")


if __name__ == "__main__":
    main()
