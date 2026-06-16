"""
P3 — conversation-state-isolation benchmark generator.

Builds a multi-turn dataset of (turn-1, turn-2) conversations to measure whether a
new-topic second question leaks the first turn's entity/topic context (the
SIA-after-FASILKOM bug). These are EVALUATION SCENARIOS grounded in REAL UMB
entities (faculties, programs, campuses) + the real canonical intents — not
fabricated "authentic user questions" (that is the separate P1 golden dataset).
Every conversation is deterministically labelled:

    expected_followup      — is turn-2 a genuine follow-up of turn-1?
    expected_intent_switch — does turn-2 move to a different concrete intent?
    prior_terms            — distinctive turn-1 tokens that must NOT appear in the
                             turn-2 retrieval query when it is a new topic.

Run:  PYTHONPATH=. python -m app.evaluation.followup_dataset
→ writes app/evaluation/followup_context_benchmark.json
"""

from __future__ import annotations

import json
from pathlib import Path

# Real UMB faculties (key tokens that must not leak across an intent switch).
FACULTIES = [
    ("Fakultas Ilmu Komputer", ["fasilkom", "ilmu komputer"]),
    ("Fakultas Ekonomi dan Bisnis", ["feb", "ekonomi", "bisnis"]),
    ("Fakultas Teknik", ["teknik"]),
    ("Fakultas Ilmu Komunikasi", ["fikom", "komunikasi"]),
    ("Fakultas Desain dan Seni Kreatif", ["fdsk", "desain", "seni kreatif"]),
    ("Sekolah Pascasarjana", ["pascasarjana"]),
]

# Real UMB study programs.
PROGRAMS = [
    ("Teknik Informatika", ["informatika"]),
    ("Sistem Informasi", ["sistem informasi"]),
    ("Akuntansi", ["akuntansi"]),
    ("Manajemen", ["manajemen"]),
    ("Teknik Industri", ["teknik industri"]),
    ("Teknik Elektro", ["teknik elektro"]),
]

# Turn-1 templates that establish a distinctive entity. (label, template, extra prior terms)
SUBJECT_Q1_FACULTY = [
    ("Siapa dekan {name}?", ["dekan"]),
    ("Apa saja program studi di {name}?", ["program studi"]),
    ("Bagaimana struktur organisasi {name}?", ["struktur"]),
]
SUBJECT_Q1_PROGRAM = [
    ("Berapa biaya kuliah program {name}?", []),
    ("Bagaimana akreditasi program {name}?", ["akreditasi"]),
    ("Siapa ketua program studi {name}?", ["kaprodi", "ketua program"]),
]

# Turn-2 NEW-TOPIC questions — a different self-contained intent, no reference to turn-1.
NEWTOPIC_Q2 = [
    "Bagaimana cara login SIA?",
    "Bagaimana cara reset password SSO?",
    "Berapa biaya kuliah per semester?",
    "Beasiswa apa saja yang tersedia di UMB?",
    "Bagaimana cara mendaftar mahasiswa baru?",
    "Bagaimana cara meminjam buku di perpustakaan?",
    "Di mana lokasi kampus Meruya?",
    "Kapan jadwal UTS semester ini?",
]

# Turn-2 genuine FOLLOW-UPS — anaphora / continuation referring to turn-1's subject.
FOLLOWUP_Q2 = [
    "Bagaimana dengan program studinya?",
    "jelaskan lebih detail",
    "yang lainnya?",
    "kalau akreditasinya bagaimana?",
    "lalu siapa wakil dekannya?",
]


def _chat_title(subject_name: str) -> str:
    return f"Informasi {subject_name} UMB"


def build_dataset() -> list[dict]:
    cases: list[dict] = []
    cid = 0

    def add(q1, q2, title, expected_followup, prior_terms):
        nonlocal cid
        cid += 1
        cases.append({
            "id": f"fc-{cid:04d}",
            "turns": [q1, q2],
            "chat_title": title,
            "expected_followup": expected_followup,
            "prior_terms": sorted(set(prior_terms)),
            "language": "id",
        })

    # Family A — NEW-TOPIC intent switches (the leakage test). Faculty subjects.
    for fac_name, fac_terms in FACULTIES:
        for tmpl, extra in SUBJECT_Q1_FACULTY:
            q1 = tmpl.format(name=fac_name)
            title = _chat_title(fac_name)
            for q2 in NEWTOPIC_Q2:
                add(q1, q2, title, expected_followup=False, prior_terms=fac_terms + extra)
    # Family A — program subjects.
    for prog_name, prog_terms in PROGRAMS:
        for tmpl, extra in SUBJECT_Q1_PROGRAM[:2]:
            q1 = tmpl.format(name=prog_name)
            title = _chat_title(prog_name)
            for q2 in NEWTOPIC_Q2:
                add(q1, q2, title, expected_followup=False, prior_terms=prog_terms + extra)

    # Family B/C — genuine FOLLOW-UPS (context SHOULD be retained → prior_terms not leakage).
    for fac_name, fac_terms in FACULTIES:
        for tmpl, _extra in SUBJECT_Q1_FACULTY:
            q1 = tmpl.format(name=fac_name)
            title = _chat_title(fac_name)
            for q2 in FOLLOWUP_Q2:
                add(q1, q2, title, expected_followup=True, prior_terms=[])
    for prog_name, _terms in PROGRAMS:
        q1 = SUBJECT_Q1_PROGRAM[1][0].format(name=prog_name)  # akreditasi question
        title = _chat_title(prog_name)
        for q2 in FOLLOWUP_Q2[:3]:
            add(q1, q2, title, expected_followup=True, prior_terms=[])

    return cases


def main() -> None:
    cases = build_dataset()
    out = Path(__file__).resolve().parent / "followup_context_benchmark.json"
    payload = {
        "description": "P3 conversation-state-isolation benchmark (multi-turn). "
                       "Family A = new-topic intent switch (leakage test); "
                       "Family B/C = genuine follow-up (context retained).",
        "n_conversations": len(cases),
        "n_new_topic": sum(1 for c in cases if not c["expected_followup"]),
        "n_followup": sum(1 for c in cases if c["expected_followup"]),
        "conversations": cases,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(cases)} conversations -> {out}")


if __name__ == "__main__":
    main()
