"""
Phase 31 STEP 3 — retrieval-failure benchmark.

Runs the exact questions that FAILED in `eval-Flk-2026-06-23T10_44_59-results.csv`
through the live retrieval stack and measures, per question:

  * official_top   — is the top retrieved source an official *.mercubuana.ac.id host?
  * grounded       — did ANY layer (FAQ / entity / vector) return usable evidence?

The default pass uses the fast structured layers (entity + FAQ) so it runs without
the dense-model load that segfaults on memory-constrained hosts. Pass ``--dense`` to
additionally exercise the HybridRetriever vector path.

The point is twofold: (1) confirm the structurally-answerable questions resolve to
official sources (target official_top >= 0.998), and (2) surface the questions that
have NO grounding in the current KB — these are the true coverage gaps that STEP 4
(knowledge expansion) must close, reported honestly rather than hidden.

    python -m app.evaluation.retrieval_failure_benchmark --out ../reports/retrieval_failure_report.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Distinct failed CLEAN base questions extracted from the Phase 31 CSV, tagged by
# the intent/category used in the failure analysis.
FAILED_QUESTIONS: list[dict] = [
    {"q": "Siapa dekan Fakultas Psikologi Universitas Mercu Buana?", "cat": "faculty"},
    {"q": "Siapa dekan Fakultas Desain dan Seni Kreatif?", "cat": "faculty"},
    {"q": "Siapa dekan Fakultas Ilmu Komunikasi Universitas Mercu Buana?", "cat": "faculty"},
    {"q": "Fakultas Ilmu Komunikasi?", "cat": "faculty"},
    {"q": "Apa saja program studi di Fakultas Ekonomi dan Bisnis?", "cat": "study_program"},
    {"q": "Apa akreditasi program studi Sistem Informasi UMB?", "cat": "study_program"},
    {"q": "Siapa ketua program studi Hubungan Masyarakat Universitas Mercu Buana?", "cat": "study_program"},
    {"q": "Jurusan Hubungan Masyarakat di Mercu Buana akreditasinya apa?", "cat": "study_program"},
    {"q": "Siapa dosen pengampu di program studi Penyiaran UMB?", "cat": "lecturer"},
    {"q": "Alamat lengkap kampus Mercu Buana Bekasi di mana?", "cat": "campus"},
    {"q": "Di kampus mana program studi Desain Komunikasi Visual diselenggarakan?", "cat": "campus"},
    {"q": "Di kampus mana program studi Teknik Industri diselenggarakan?", "cat": "campus"},
    {"q": "Berapa biaya kuliah program studi Teknik Informatika di UMB?", "cat": "tuition"},
    {"q": "Berapa biaya kuliah program studi Penyiaran di UMB?", "cat": "tuition"},
    {"q": "berapa uang kuliah mercu buana", "cat": "tuition"},
    {"q": "Bagaimana cara mendaftar beasiswa KIP Kuliah di UMB?", "cat": "scholarship"},
    {"q": "Berapa daya tampung program studi Psikologi di UMB?", "cat": "admissions"},
    {"q": "Apa syarat masuk Fakultas Ekonomi dan Bisnis di Mercu Buana?", "cat": "admissions"},
    {"q": "Bagaimana cara menghubungi Biro Administrasi Akademik (BAA) UMB?", "cat": "student_services"},
    {"q": "Apa layanan konseling mahasiswa yang tersedia di UMB?", "cat": "student_services"},
    {"q": "Layanan akademik apa yang tersedia untuk mahasiswa Teknik Informatika?", "cat": "student_services"},
    {"q": "Apa saja layanan perpustakaan digital UMB?", "cat": "library"},
    {"q": "Bagaimana prosedur layanan E-Learning UMB di UMB?", "cat": "general"},
    {"q": "Bagaimana mahasiswa Fakultas Teknik mengakses SIA UMB?", "cat": "sia"},
    {"q": "Bagaimana mahasiswa Teknik Elektro mengaktifkan akun SSO UMB?", "cat": "sso"},
    {"q": "Bagaimana mahasiswa Fakultas Ilmu Komputer login SSO untuk mengakses layanan UMB?", "cat": "sso"},
    {"q": "Kapan jadwal perkuliahan untuk mahasiswa Hubungan Masyarakat dimulai?", "cat": "academic_calendar"},
    {"q": "Kapan jadwal perkuliahan untuk mahasiswa Akuntansi dimulai?", "cat": "academic_calendar"},
    {"q": "Di mana kalender akademik untuk Fakultas Ilmu Komunikasi?", "cat": "academic_calendar"},
    {"q": "Apa ketentuan kelulusan untuk mahasiswa Fakultas Ekonomi dan Bisnis?", "cat": "academic_regulations"},
    {"q": "Apa ketentuan kelulusan untuk mahasiswa Fakultas Teknik?", "cat": "academic_regulations"},
    {"q": "Apa peraturan akademik yang berlaku untuk program studi Teknik Mesin?", "cat": "academic_regulations"},
]

_OFFICIAL = "mercubuana.ac.id"


def _is_official(host: str) -> bool:
    h = (host or "").lower()
    return h == _OFFICIAL or h.endswith("." + _OFFICIAL)


def _host_of(ctx: dict) -> str:
    h = ctx.get("hostname") or ""
    if not h:
        url = ctx.get("url") or ""
        h = url.split("/")[2] if "://" in url else ""
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/retrieval_failure_report.json")
    ap.add_argument("--dense", action="store_true", help="also run the HybridRetriever vector path")
    ap.add_argument("--target", type=float, default=0.998)
    args = ap.parse_args()

    report = {"target_official_top": args.target, "n_questions": len(FAILED_QUESTIONS)}
    try:
        from app.db.database import get_session_local

        db = get_session_local()()
    except Exception as exc:
        report.update(status="skipped", reason=f"DB unavailable: {exc}")
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[retrieval] SKIPPED — DB unavailable: {exc}")
        return

    from app.rag.query_normalizer import normalize_query
    from app.retrieval.entity_retriever import query_entities

    try:
        from app.retrieval.faq_retriever import match_faq
    except Exception:
        match_faq = None  # type: ignore

    hybrid = None
    if args.dense:
        try:
            from app.retrieval.hybrid_retriever import HybridRetriever

            hybrid = HybridRetriever(db)
        except Exception as exc:
            report["dense_init_error"] = str(exc)

    rows = []
    official_hits = 0
    grounded = 0
    gaps = []
    for item in FAILED_QUESTIONS:
        q = normalize_query(item["q"])
        contexts: list[dict] = []
        try:
            contexts += query_entities(db, q)
        except Exception:
            pass
        if match_faq is not None:
            try:
                contexts += [c for c in match_faq(db, item["q"]) if not c.get("intent_demoted")]
            except Exception:
                pass
        if hybrid is not None:
            try:
                contexts += hybrid.retrieve(q, top_k=5) or []
            except Exception as exc:
                report.setdefault("dense_errors", []).append({"q": item["q"], "err": str(exc)})

        top = contexts[0] if contexts else {}
        host = _host_of(top)
        is_off = _is_official(host)
        has_ground = bool(contexts)
        official_hits += int(is_off)
        grounded += int(has_ground)
        if not has_ground:
            gaps.append(item)
        rows.append({"q": item["q"], "cat": item["cat"], "official_top": is_off,
                     "grounded": has_ground, "top_host": host})
    db.close()

    n = len(FAILED_QUESTIONS)
    official_top = round(official_hits / n, 4)
    coverage = round(grounded / n, 4)
    report.update(
        status="ok",
        dense=bool(hybrid),
        official_top=official_top,
        structured_coverage=coverage,
        meets_official_top=official_top >= args.target,
        coverage_gaps=[g["q"] for g in gaps],
        coverage_gap_categories=sorted({g["cat"] for g in gaps}),
        per_question=rows,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"official_top (of grounded): {official_top} | structured coverage: {coverage}")
    print(f"coverage gaps ({len(gaps)}): {sorted({g['cat'] for g in gaps})}")


if __name__ == "__main__":
    main()
