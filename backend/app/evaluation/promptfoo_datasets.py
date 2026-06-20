"""Phase 21 — generate Promptfoo datasets from the real entity data.

Writes promptfoo-format test files (tests: [{vars, assert}]) to
evaluation/promptfoo/datasets/. Each test carries machine-checkable assertions
(expected entity type / faculty / official-source) consumed both by `npx
promptfoo eval` (CI) and the deterministic local runner.

    python -m app.evaluation.promptfoo_datasets
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.database import get_session_local
from app.db.models import UMBFaculty, UMBStudyProgram
from app.retrieval.entity_retriever import _PROGRAM_NAME_MAP

_OUT = Path(__file__).resolve().parents[3] / "evaluation" / "promptfoo" / "datasets"

_FAC_ALIASES = {
    "FEB": ["FEB", "Fakultas Ekonomi dan Bisnis"],
    "FT": ["FT", "Fakultas Teknik"],
    "FASILKOM": ["FASILKOM", "Fakultas Ilmu Komputer"],
    "FIKOM": ["FIKOM", "Fakultas Ilmu Komunikasi"],
    "FDSK": ["FDSK", "Fakultas Desain dan Seni Kreatif"],
    "FPSI": ["FPSI", "Fakultas Psikologi"],
    "PASCA": ["Pascasarjana"],
}
_RETRIEVAL_TOPICS = [
    ("Bagaimana cara daftar mahasiswa baru di UMB?", "admissions"),
    ("Berapa biaya kuliah kelas karyawan?", "tuition"),
    ("Kapan jadwal PMB 2026?", "admissions"),
    ("Bagaimana cara login SIA?", "sia"),
    ("Apa itu SSO UMB?", "sso"),
    ("Beasiswa apa saja yang tersedia di UMB?", "scholarship"),
    ("Di mana kampus UMB Meruya?", "campus"),
    ("Bagaimana prosedur pengurusan transkrip nilai?", "student_services"),
    ("Apa aturan cuti akademik di UMB?", "academic_regulations"),
    ("Panduan akademik UMB di mana?", "academic_regulations"),
]


def _t(query, asserts):
    return {"vars": {"query": query}, "assert": asserts}


def build(db) -> dict:
    faculties = db.query(UMBFaculty).all()
    programs = [p.program_name for p in db.query(UMBStudyProgram).all()]
    prog_names = sorted(set(programs))

    retrieval, entity, followup, accreditation = [], [], [], []

    # --- entity (>=200): deans + faculty identity + kaprodi + program identity ---
    dean_tmpl = ["Siapa dekan {x}?", "Dekan {x}", "Nama dekan {x}", "Pimpinan {x}",
                 "Siapa pimpinan {x}?", "Dekan {x} siapa?"]
    fac_id_tmpl = ["Tentang {x}", "Profil {x}", "Jelaskan {x}", "Detail {x}"]
    for short, aliases in _FAC_ALIASES.items():
        for a in aliases:
            for t in dean_tmpl:
                entity.append(_t(t.format(x=a), [
                    {"type": "entity_type", "value": "faculty"},
                    {"type": "faculty", "value": short},
                    {"type": "official-source"},
                ]))
            for t in fac_id_tmpl:
                entity.append(_t(t.format(x=a), [
                    {"type": "entity_type", "value": "faculty"},
                    {"type": "faculty", "value": short}, {"type": "official-source"}]))
    prog_tmpl = ["Siapa kaprodi {x}?", "Ketua program studi {x}", "Program studi {x}",
                 "Profil prodi {x}", "Kaprodi {x}", "Jurusan {x}"]
    for kw, name in _PROGRAM_NAME_MAP.items():
        for t in prog_tmpl:
            entity.append(_t(t.format(x=name), [
                {"type": "entity_type", "value": "study_program"},
                {"type": "contains", "value": name},
                {"type": "official-source"},
            ]))

    # --- accreditation (>=100) ---
    acc_tmpl = ["Akreditasi {x}", "Akreditasi program studi {x}", "Status akreditasi {x}",
                "Peringkat akreditasi {x}", "Akreditasi prodi {x}", "Akreditasi jurusan {x}"]
    for name in prog_names:
        for t in acc_tmpl:
            accreditation.append(_t(t.format(x=name), [
                {"type": "entity_type", "value": "study_program"},
                {"type": "contains", "value": name},
                {"type": "official-source"},
            ]))
    for short, aliases in _FAC_ALIASES.items():
        for a in aliases:
            accreditation.append(_t(f"Akreditasi fakultas {a}", [
                {"type": "entity_type", "value": "faculty"}, {"type": "official-source"}]))

    # --- follow-up (>=100): elliptical, resolved via session memory ---
    fu_forms = ["Siapa dekannya?", "Beliau menjabat sejak kapan?", "Bagaimana akreditasinya?",
                "Di mana profilnya?", "Kalau kampusnya?", "Apa visi misinya?", "Bagaimana sejarahnya?",
                "Apa saja programnya?", "Bagaimana kontaknya?"]
    for short, aliases in _FAC_ALIASES.items():
        for fu in fu_forms:
            followup.append({
                "vars": {"establish": f"Ceritakan tentang {aliases[-1]}", "query": fu},
                "assert": [{"type": "faculty", "value": short}, {"type": "official-source"}],
            })
    prog_fu = ["Siapa kaprodinya?", "Akreditasinya bagaimana?", "Kalau yang kelas karyawan?"]
    for kw, name in _PROGRAM_NAME_MAP.items():
        for fu in prog_fu:
            followup.append({
                "vars": {"establish": f"Bagaimana dengan program studi {name}?", "query": fu},
                "assert": [{"type": "contains", "value": name}, {"type": "official-source"}],
            })

    # --- retrieval (>=500): topical + per-faculty/program official-source ---
    for q, cat in _RETRIEVAL_TOPICS:
        retrieval.append(_t(q, [{"type": "official-source"}, {"type": "no-hallucination"}]))
    # expand to >=500 with faculty/program/topic variants
    variants = ["Informasi {x}", "Jelaskan {x}", "Profil {x}", "Detail {x}", "Tentang {x}"]
    for short, aliases in _FAC_ALIASES.items():
        for a in aliases:
            for v in variants:
                retrieval.append(_t(v.format(x=a), [{"type": "official-source"}]))
    for name in prog_names:
        for v in variants:
            retrieval.append(_t(v.format(x=name), [{"type": "official-source"}]))
    # pad with topical repeats across phrasings to clear 500
    extra_phrasings = ["{q}", "Tolong jelaskan: {q}", "Mohon info {q}", "Saya ingin tahu {q}"]
    while len(retrieval) < 500:
        for q, _cat in _RETRIEVAL_TOPICS:
            for ph in extra_phrasings:
                retrieval.append(_t(ph.format(q=q.rstrip("?")) + "?", [{"type": "official-source"}]))
                if len(retrieval) >= 500:
                    break
            if len(retrieval) >= 500:
                break

    return {
        "retrieval": retrieval[:520],
        "entity": entity[:240],
        "followup": followup[:120],
        "accreditation": accreditation[:140],
    }


def main() -> None:
    db = get_session_local()()
    try:
        sets = build(db)
    finally:
        db.close()
    _OUT.mkdir(parents=True, exist_ok=True)
    for name, tests in sets.items():
        (_OUT / f"{name}.json").write_text(json.dumps({"tests": tests}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {name}: {len(tests)} tests -> datasets/{name}.json")
    total = sum(len(v) for v in sets.values())
    print(f"total promptfoo tests: {total}")


if __name__ == "__main__":
    main()
