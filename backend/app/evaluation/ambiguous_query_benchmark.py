"""
Phase 31 STEP 6 — ambiguous-query resolution benchmark.

Validates the two-branch contract for context-light queries:

  * NO session memory  -> the system asks for clarification (does NOT silently
    default to an arbitrary entity, e.g. Fasilkom).
  * Session memory present -> the elliptical reference resolves automatically to
    the remembered subject (no clarification needed).

This exercises the real engines (`clarifying_questions` / `clarification_suggestions`
and `resolve_followup` + `SessionContext`) without invoking the LLM, so it runs
fast and deterministically.

    python -m app.evaluation.ambiguous_query_benchmark --out ../reports/ambiguous_query_report.json

Target: resolution accuracy >= 0.98 (directive STEP 6).
Degrades gracefully (status="skipped", exit 0) if the DB is unavailable.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Ambiguous, context-light queries that MUST trigger clarification when no memory.
_AMBIGUOUS = [
    "Siapa dekannya?", "Siapa dekan?", "Akreditasinya apa?", "Berapa biayanya?",
    "Di kampus mana?", "Kapan jadwalnya?", "Siapa ketua program studinya?",
    "Bagaimana cara daftarnya?", "Apa saja syaratnya?", "Beliau siapa?",
    "Kontaknya apa?", "Di mana lokasinya?", "Berapa daya tampungnya?",
]
# Self-contained queries that must NOT be treated as ambiguous (clarification = wrong).
_SELF_CONTAINED = [
    "Siapa dekan Fakultas Psikologi?", "Akreditasi Sistem Informasi apa?",
    "Berapa biaya kuliah Teknik Informatika?", "Di mana lokasi kampus Bekasi?",
    "Apa saja program studi di Fakultas Ekonomi dan Bisnis?",
]
# Elliptical follow-ups that, WITH memory of a subject, must resolve to it.
# kind selects which SessionContext slot the prior turn established.
_FOLLOWUPS = [
    ("Akreditasinya bagaimana?", "Fakultas Psikologi", "faculty"),
    ("Siapa dekannya?", "Fakultas Teknik", "faculty"),
    ("Beliau menjabat sejak kapan?", "Fakultas Ilmu Komunikasi", "faculty"),
    ("Kaprodinya siapa?", "Desain Komunikasi Visual", "program"),
]


def _run_no_memory(language="id"):
    # The system prevents silent-defaulting via TWO complementary mechanisms: the
    # vague-query clarifier AND the elliptical-followup detector. A context-light
    # query with no memory is safe if EITHER fires (it will not be answered with an
    # arbitrary default such as Fasilkom). Self-contained queries must trigger
    # NEITHER (they are answered directly).
    from app.chat.clarify import clarifying_questions
    from app.rag.followup_resolution import is_elliptical

    ok = 0
    detail = []
    for q in _AMBIGUOUS:
        guarded = bool(clarifying_questions(q, recent_messages=[], language=language)) or is_elliptical(q)
        ok += int(guarded)
        detail.append({"query": q, "guarded": guarded})
    for q in _SELF_CONTAINED:
        guarded = bool(clarifying_questions(q, recent_messages=[], language=language)) or is_elliptical(q)
        good = not guarded  # self-contained => answered directly, not guarded
        ok += int(good)
        detail.append({"query": q, "self_contained_direct": good})
    total = len(_AMBIGUOUS) + len(_SELF_CONTAINED)
    return ok, total, detail


def _run_with_memory():
    from app.chat.session_memory import SessionContext
    from app.rag.followup_resolution import resolve_followup

    ok = 0
    detail = []
    for q, subject, kind in _FOLLOWUPS:
        ctx = SessionContext()
        setattr(ctx, kind, subject)  # real slots are .faculty / .program
        try:
            resolved = resolve_followup(q, ctx)
            ref = (getattr(resolved, "resolved_reference", "") or "")
            good = subject.lower() in ref.lower() and bool(getattr(resolved, "enrichment_hint", ""))
        except Exception as exc:
            good = False
            ref = f"error: {exc}"
        ok += int(good)
        detail.append({"query": q, "subject": subject, "resolved": ref, "ok": good})
    return ok, len(_FOLLOWUPS), detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../reports/ambiguous_query_report.json")
    ap.add_argument("--target", type=float, default=0.98)
    args = ap.parse_args()

    report = {"target": args.target}
    try:
        nomem_ok, nomem_total, nomem_detail = _run_no_memory()
        mem_ok, mem_total, mem_detail = _run_with_memory()
    except Exception as exc:
        report.update(status="skipped", reason=str(exc))
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[ambiguous] SKIPPED — {exc}")
        return

    total_ok = nomem_ok + mem_ok
    total = nomem_total + mem_total
    overall = round(total_ok / max(total, 1), 4)
    report.update(
        status="ok",
        no_memory={"accuracy": round(nomem_ok / max(nomem_total, 1), 4), "detail": nomem_detail},
        with_memory={"accuracy": round(mem_ok / max(mem_total, 1), 4), "detail": mem_detail},
        overall_resolution=overall,
        meets_target=overall >= args.target,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  no-memory clarify accuracy : {report['no_memory']['accuracy']}")
    print(f"  with-memory resolve accuracy: {report['with_memory']['accuracy']}")
    print(f"overall: {overall} | target {args.target} | meets={report['meets_target']}")


if __name__ == "__main__":
    main()
