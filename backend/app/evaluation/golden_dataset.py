"""
P1 — UMB Golden Dataset framework.

Builds a production-grade evaluation dataset from AUTHENTIC, in-repo, KB-grounded
sources (never fabricated user data). Synthetic paraphrase variants are allowed only
when explicitly tagged ``synthetic: true`` with a ``derived_from`` pointer for full
traceability.

Authentic sources (``synthetic=false``):
  - benchmark_seed   : app/evaluation/umb_benchmark.json (501 curated, KB-grounded)
  - official_faq     : faq_seed.FAQ_SEEDS canonical questions
  - faq_alias        : faq_seed.FAQ_SEEDS aliases (curated real phrasings)
  - entity_lookup    : canonical lookup questions over real faculties / programs /
                       campuses / scholarships / contacts / services
Synthetic (``synthetic=true``):
  - synthetic_variant: deterministic paraphrases of an authentic question (same intent
                       + expected_sources), each carrying ``derived_from``.

Run:  PYTHONPATH=. python -m app.evaluation.golden_dataset [--target 1200]
→ writes data/golden_dataset/{golden_dataset.jsonl, golden_dataset_stats.json,
  golden_dataset_followups.jsonl}
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

DATASET_VERSION = "golden-v2"
_BUILD_TS = datetime.now(timezone.utc).isoformat()

_EVAL_DIR = Path(__file__).resolve().parent
_OUT_DIR = _EVAL_DIR.parents[2] / "data" / "golden_dataset"

# benchmark category / FAQ intent -> canonical intent (intent_router vocabulary).
_INTENT_MAP = {
    "admissions": "admissions", "admission": "admissions",
    "tuition": "tuition", "scholarship": "scholarship",
    "academic_calendar": "academic_calendar", "academic_regulations": "academic_regulations",
    "campus_information": "campus", "campus": "campus",
    "faculties": "faculty", "faculty": "faculty",
    "study_programs": "study_program", "study_program": "study_program",
    "lecturers_staff": "lecturer", "lecturer": "lecturer",
    "student_services": "student_services", "student_service": "student_services",
    "sia": "sia", "sso": "sso", "library": "library", "research": "research",
}
_CONTROL_CATEGORIES = {"out_of_scope", "private_credential", "unanswerable"}


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        net = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
        return net or None
    except Exception:
        return None


def _norm_intent(raw: str | None) -> str:
    return _INTENT_MAP.get((raw or "").strip().lower(), "general")


def _record(rid, question, intent, expected_sources, answerable, synthetic, source_type, **extra):
    rec = {
        "id": rid,
        "question": question.strip(),
        "intent": intent,
        "expected_sources": sorted({h for h in (expected_sources or []) if h}),
        "answerable": bool(answerable),
        "synthetic": bool(synthetic),
        "source_type": source_type,
        "created_at": _BUILD_TS,
        "dataset_version": DATASET_VERSION,
    }
    rec.update(extra)
    return rec


# --- authentic loaders -------------------------------------------------------
def from_benchmark_seed() -> list[dict]:
    data = json.loads((_EVAL_DIR / "umb_benchmark.json").read_text(encoding="utf-8"))
    out = []
    for i, q in enumerate(data, start=1):
        cat = (q.get("category") or "").lower()
        control = cat in _CONTROL_CATEGORIES
        out.append(_record(
            f"bench_{i:05d}", q.get("question") or "",
            "general" if control else _norm_intent(cat),
            q.get("expected_hosts") or [],
            answerable=not control,
            synthetic=False, source_type="benchmark_seed",
            category=cat, lang=q.get("lang", "id"),
        ))
    return out


def from_faqs() -> list[dict]:
    from app.ingestion.faq_seed import FAQ_SEEDS

    out = []
    for fi, faq in enumerate(FAQ_SEEDS, start=1):
        intent = _norm_intent(faq.get("intent") or faq.get("category"))
        hosts = [_host(u) for u in (faq.get("source_urls") or [])]
        out.append(_record(
            f"faq_{fi:03d}", faq["canonical_question"], intent, hosts,
            answerable=True, synthetic=False, source_type="official_faq",
        ))
        for ai, alias in enumerate(faq.get("aliases") or [], start=1):
            out.append(_record(
                f"faq_{fi:03d}_alias_{ai:02d}", alias, intent, hosts,
                answerable=True, synthetic=False, source_type="faq_alias",
                derived_from=f"faq_{fi:03d}",
            ))
    return out


def from_entities() -> list[dict]:
    from app.ingestion import entity_extractor as e

    out: list[dict] = []
    n = 0

    def add(q, intent, hosts):
        nonlocal n
        n += 1
        out.append(_record(
            f"ent_{n:04d}", q, intent, hosts, answerable=True,
            synthetic=False, source_type="entity_lookup",
        ))

    for f in e.FACULTY_SEEDS:
        name, host = f["name"], _host(f.get("website_url")) or "mercubuana.ac.id"
        add(f"Siapa dekan {name}?", "lecturer", [host])
        add(f"Apa saja program studi di {name}?", "study_program", [host])
    for p in e.PROGRAM_SEEDS:
        add(f"Program studi {p['program_name']} ada di fakultas apa?", "study_program", ["mercubuana.ac.id"])
        add(f"Berapa biaya kuliah program {p['program_name']} di UMB?", "tuition",
            ["pendaftaran.mercubuana.ac.id"])
    for c in e.CAMPUS_SEEDS:
        add(f"Di mana lokasi kampus {c['campus_name']} UMB?", "campus", [_host(c.get("website_url")) or "mercubuana.ac.id"])
    for s in e.SCHOLARSHIP_SEEDS:
        hosts = [_host(u) for u in (s.get("source_urls") or [])] or ["mercubuana.ac.id"]
        add(f"Apa syarat beasiswa {s['scholarship_name']} di UMB?", "scholarship", hosts)
    for c in e.CONTACT_SEEDS:
        add(f"Bagaimana cara menghubungi {c['office_name']} UMB?", "student_services", [_host(c.get("url"))])
    for s in e.SERVICE_SEEDS:
        add(f"Bagaimana prosedur layanan {s['service_name']} di UMB?",
            _norm_intent(s.get("category")), [_host(s.get("url"))])
    return out


# --- synthetic expansion -----------------------------------------------------
_PARAPHRASE_TEMPLATES = (
    "Tolong jelaskan, {q_lower}",
    "Saya ingin bertanya: {q}",
    "Mohon informasi, {q_lower}",
    "Bisakah dijelaskan {q_lower}",
    "{q_noq} ya?",
)


def synthetic_variants(authentic: list[dict], *, target_total: int) -> list[dict]:
    """Deterministic paraphrases of authentic, answerable questions until the dataset
    reaches ``target_total``. Each keeps the base intent + expected_sources and links
    back via ``derived_from`` (full traceability)."""
    seeds = [r for r in authentic if r["answerable"] and r["source_type"] != "synthetic_variant"]
    out: list[dict] = []
    seen = {r["question"].strip().lower() for r in authentic}
    need = max(0, target_total - len(authentic))
    si = 0
    for round_idx in range(len(_PARAPHRASE_TEMPLATES)):
        if len(out) >= need:
            break
        tmpl = _PARAPHRASE_TEMPLATES[round_idx]
        for base in seeds:
            if len(out) >= need:
                break
            q = base["question"].rstrip("?").strip()
            variant = tmpl.format(q=base["question"], q_lower=q[0].lower() + q[1:] if q else q, q_noq=q)
            key = variant.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            si += 1
            out.append(_record(
                f"syn_{si:05d}", variant, base["intent"], base["expected_sources"],
                answerable=base["answerable"], synthetic=True,
                source_type="synthetic_variant", derived_from=base["id"],
            ))
    return out


# --- multi-turn follow-up format --------------------------------------------
def build_followups() -> list[dict]:
    """Re-emit the P3 follow-up benchmark in the golden multi-turn schema, integrating
    directly with ``followup_context_benchmark.json``."""
    from app.rag.intent_router import detect_intent

    path = _EVAL_DIR / "followup_context_benchmark.json"
    if not path.exists():
        return []
    convs = json.loads(path.read_text(encoding="utf-8")).get("conversations", [])
    out = []
    for c in convs:
        turns = c["turns"]
        out.append({
            "id": c["id"],
            "conversation": turns,
            "expected_followup": bool(c["expected_followup"]),
            "expected_intent": detect_intent(turns[-1]),
            "dataset_version": DATASET_VERSION,
            "created_at": _BUILD_TS,
        })
    return out


def _dedupe(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for r in records:
        key = r["question"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def build_dataset(*, target_total: int = 1200) -> list[dict]:
    # FAQs first so the authoritative ``official_faq`` canonical survives de-dup (a
    # benchmark paraphrase of the same question is the duplicate dropped), keeping every
    # ``faq_alias.derived_from`` pointer valid.
    authentic = _dedupe(from_faqs() + from_benchmark_seed() + from_entities())
    synthetic = synthetic_variants(authentic, target_total=target_total)
    return authentic + synthetic


def statistics(records: list[dict]) -> dict:
    total = len(records)
    synth = sum(1 for r in records if r["synthetic"])
    answerable = sum(1 for r in records if r["answerable"])
    return {
        "total": total,
        "authentic": total - synth,
        "synthetic": synth,
        "synthetic_ratio": round(synth / total, 4) if total else 0.0,
        "answerable_ratio": round(answerable / total, 4) if total else 0.0,
        "intent_distribution": dict(Counter(r["intent"] for r in records)),
        "source_distribution": dict(Counter(r["source_type"] for r in records)),
        "dataset_version": DATASET_VERSION,
        "generated_at": _BUILD_TS,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the UMB golden dataset")
    ap.add_argument("--target", type=int, default=1200, help="target total (authentic + synthetic)")
    args = ap.parse_args()

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = build_dataset(target_total=args.target)
    followups = build_followups()
    stats = statistics(records)
    stats["followup_conversations"] = len(followups)

    with (_OUT_DIR / "golden_dataset.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (_OUT_DIR / "golden_dataset_followups.jsonl").open("w", encoding="utf-8") as fh:
        for r in followups:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (_OUT_DIR / "golden_dataset_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"golden_dataset.jsonl       : {stats['total']} "
          f"({stats['authentic']} authentic / {stats['synthetic']} synthetic)")
    print(f"answerable_ratio           : {stats['answerable_ratio']}")
    print(f"synthetic_ratio            : {stats['synthetic_ratio']}")
    print(f"source_distribution        : {stats['source_distribution']}")
    print(f"followup_conversations     : {len(followups)}")
    print(f"-> {_OUT_DIR}")


if __name__ == "__main__":
    main()
