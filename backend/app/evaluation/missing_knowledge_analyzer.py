"""
Phase 33 P33.3 — missing-coverage analyzer.

Mines a Promptfoo results CSV for the questions that FAILED because the KB lacked the
answer (refusals / wrong-topic answers), and ranks the missing topics, entities and
programs by frequency. Output drives the targeted crawl (Phase 34) and the FAQ-gap
backlog. Pure analysis — no DB, no network.

    python -m app.evaluation.missing_knowledge_analyzer \
        --csv ../eval-Flk-2026-06-23T10_44_59-results.csv \
        --out ../reports/missing_knowledge_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

# Refusal / non-answer signatures (an answer that did not actually answer).
_REFUSAL_MARKERS = (
    "belum menemukan", "tidak menebak", "belum tersedia", "belum memuat",
    "could not find", "context is required", "internal server error", "read timed out",
    "tidak dapat", "silakan cek halaman", "hubungi admin",
)
# Topic taxonomy keyed by signal words in the query.
_TOPIC_PATTERNS = {
    "tuition": ("biaya", "uang kuliah", "tuition", "spp", "cost"),
    "scholarship": ("beasiswa", "kip", "scholarship"),
    "academic_calendar": ("kalender", "jadwal perkuliahan", "jadwal", "calendar"),
    "graduation_rules": ("kelulusan", "wisuda", "graduation", "yudisium"),
    "academic_regulations": ("peraturan akademik", "ketentuan", "regulation"),
    "digital_library": ("perpustakaan", "library", "digilib", "repository"),
    "student_services": ("layanan", "konseling", "baa", "biro", "counseling", "service"),
    "admission_quota": ("daya tampung", "kuota", "quota", "syarat masuk", "daftar"),
    "lecturer": ("dosen", "lecturer"),
    "dean_faculty": ("dekan", "dean", "fakultas", "faculty"),
    "study_program": ("program studi", "prodi", "jurusan", "akreditasi", "ketua program"),
    "sia_sso_elearning": ("sia", "sso", "e-learning", "elearning", "krs"),
    "campus": ("kampus", "lokasi", "alamat", "campus"),
}
_FACULTIES = ["psikologi", "desain dan seni kreatif", "ilmu komunikasi", "ilmu komputer",
              "ekonomi dan bisnis", "teknik"]
_PROGRAMS = ["teknik informatika", "sistem informasi", "penyiaran", "hubungan masyarakat",
             "desain komunikasi visual", "akuntansi", "manajemen", "teknik mesin",
             "teknik elektro", "teknik industri", "teknik sipil", "psikologi", "sains data"]


def _is_failed_nonanswer(output: str, verdict: str) -> bool:
    low = (output or "").lower()
    if verdict.strip().lower() != "fail":
        return False
    return any(m in low for m in _REFUSAL_MARKERS) or "[fail]" in low or "[error]" in low


def _topic_of(q: str) -> str:
    low = (q or "").lower()
    for topic, sigs in _TOPIC_PATTERNS.items():
        if any(s in low for s in sigs):
            return topic
    return "other"


def analyze_csv(path: Path) -> dict:
    topics, entities, programs, queries = Counter(), Counter(), Counter(), Counter()
    seen_fail = 0
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None) or []
        pass_cols = [i for i, h in enumerate(header) if h.strip().lower() == "pass"]
        for row in reader:
            if not row:
                continue
            q = row[0]
            for pc in pass_cols:
                if pc >= len(row):
                    continue
                verdict = row[pc]
                output = row[pc - 1] if pc - 1 >= 0 else ""
                if _is_failed_nonanswer(output, verdict):
                    seen_fail += 1
                    low = q.lower()
                    topics[_topic_of(q)] += 1
                    queries[q.strip()] += 1
                    for f in _FACULTIES:
                        if f in low:
                            entities[f"faculty:{f}"] += 1
                    for p in _PROGRAMS:
                        if p in low:
                            programs[f"program:{p}"] += 1
    return {
        "failed_nonanswer_verdicts": seen_fail,
        "missing_topics_ranked": topics.most_common(),
        "missing_entities_ranked": entities.most_common(),
        "missing_programs_ranked": programs.most_common(),
        "top_missed_queries": queries.most_common(15),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", default="../reports/missing_knowledge_report.json")
    args = ap.parse_args()
    report = analyze_csv(Path(args.csv))
    report["crawl_targets"] = [
        "baa.mercubuana.ac.id", "pmb.mercubuana.ac.id", "library.mercubuana.ac.id",
        "elearning.mercubuana.ac.id", "sia.mercubuana.ac.id",
        "psikologi.mercubuana.ac.id", "feb.mercubuana.ac.id", "ft.mercubuana.ac.id",
        "fikom.mercubuana.ac.id", "fdsk.mercubuana.ac.id",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"failed non-answer verdicts: {report['failed_nonanswer_verdicts']}")
    print("top missing topics:", report["missing_topics_ranked"][:6])
    print("top missing entities:", report["missing_entities_ranked"][:5])


if __name__ == "__main__":
    main()
