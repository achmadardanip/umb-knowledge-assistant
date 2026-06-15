"""
Batch 5 — entity-enrichment crawl for faculty/program leadership.

Phase-5 found the indexed chunks don't carry dean / kaprodi names in an
extractable form. This module targets the leadership pages directly
(`struktur-organisasi`, `pimpinan`, `dekanat`, `sambutan-dekan`, …) per faculty
subdomain, extracts the dean name, and updates ``umb_faculties.dean``
(confidence 0.6). Rebuild the typed graph afterwards.

Usage (from backend/):
  PYTHONPATH=. .venv/Scripts/python.exe -m app.ingestion.leadership_enrichment \
      --out ../data/reports/leadership_enrichment.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Candidate leadership paths probed per faculty site.
LEADERSHIP_PATHS = (
    "struktur-organisasi",
    "struktur-organisasi/",
    "pimpinan",
    "pimpinan-fakultas",
    "dekanat",
    "sambutan-dekan",
    "profil/struktur-organisasi",
    "tentang/struktur-organisasi",
    "",  # the faculty homepage itself
)

_DEGREE = (
    r"(?:Prof\.?|Dr\.?|Ir\.?|S\.Kom|S\.T\.?|ST|M\.Kom|MMSI|MTI|M\.T\.?|M\.Sc|Ph\.?D|"
    r"MM|M\.M|M\.Si|S\.Si|S\.E|SE|S\.H|M\.Hum|M\.Eng|IPM|S\.Sos|M\.Ikom)"
)
# "Dekan[:/-] <Prof. Dr. Name, M.Kom>" — name has at least one degree token nearby.
_DEAN_RE = re.compile(
    r"[Dd]ekan(?:\s+[A-Za-z ]{0,40})?\s*[:\-–—]?\s*"
    rf"((?:Prof\.?\s*)?(?:Dr\.?\s*)?(?:Ir\.?\s*)?[A-Z][A-Za-z.''-]+(?:\s+[A-Z][A-Za-z.''-]+){{1,5}}"
    rf"(?:\s*,\s*{_DEGREE}(?:\s*,\s*{_DEGREE})*)?)",
)
_ROLE_BOUNDARY = re.compile(
    r"\b(wakil\s+dekan|ketua\s+program|kaprodi|sekretaris|kepala|dosen|nidn|jabatan|fakultas|program\s+studi)\b",
    re.IGNORECASE,
)


def _clean_dean(raw: str) -> str | None:
    cand = re.sub(r"\s+", " ", raw or "").strip(" :-–—|,;")
    cand = re.sub(r"^(?:fakultas[\w\s]+?|universitas mercu buana)\s+", "", cand, flags=re.IGNORECASE)
    b = _ROLE_BOUNDARY.search(cand)
    if b and b.start() > 0:
        cand = cand[: b.start()].strip(" :-–—|,;")
    cand = re.sub(r"\s+", " ", cand).strip(" :-–—|,;")
    if not cand or len(cand.split()) < 2:
        return None
    low = cand.lower()
    if any(t in low for t in ("fakultas", "program studi", "dosen", "universitas", "struktur")):
        return None
    if len(cand) > 90:
        return None
    return cand


def extract_dean(text: str) -> str | None:
    for m in _DEAN_RE.finditer(text or ""):
        cleaned = _clean_dean(m.group(1))
        if cleaned:
            return cleaned
    return None


def _faculty_candidate_urls(website_url: str) -> list[str]:
    if not website_url:
        return []
    p = urlparse(website_url)
    base = f"{p.scheme or 'https'}://{p.netloc}"
    return [f"{base}/{path}" if path else f"{base}/" for path in LEADERSHIP_PATHS]


def enrich_faculty_deans(db: Session, *, fetcher=None, confidence: float = 0.6, dry_run: bool = False) -> dict:
    """Probe each faculty's leadership pages and fill its ``dean`` if extractable.

    ``fetcher(url) -> str`` returns page text; defaults to the live web fetcher.
    """
    from app.db.models import UMBFaculty

    if fetcher is None:
        def fetcher(url: str) -> str:
            from app.web_search.live_fetcher import fetch_live_contexts

            ctxs = fetch_live_contexts(url, title=None, score=0.5)
            return "\n".join(c.get("chunk_text") or "" for c in ctxs)

    report: dict = {"updated": [], "not_found": [], "errors": []}
    for faculty in db.query(UMBFaculty).all():
        if faculty.dean:  # already known
            continue
        found = None
        for url in _faculty_candidate_urls(faculty.website_url or ""):
            try:
                text = fetcher(url)
            except Exception as exc:
                report["errors"].append({"faculty": faculty.name, "url": url, "error": str(exc)[:160]})
                continue
            dean = extract_dean(text)
            if dean:
                found = {"faculty": faculty.name, "dean": dean, "url": url}
                break
        if found:
            if not dry_run:
                faculty.dean = found["dean"]
                faculty.confidence = max(float(faculty.confidence or 0.0), confidence)
                db.flush()
            report["updated"].append(found)
        else:
            report["not_found"].append(faculty.name)
    if not dry_run:
        db.commit()
    return report


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Enrich faculty dean fields from leadership pages")
    ap.add_argument("--out", default="../data/reports/leadership_enrichment.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from app.db.database import get_session_local
    from pathlib import Path

    db = get_session_local()()
    try:
        report = enrich_faculty_deans(db, dry_run=args.dry_run)
    finally:
        db.close()
    logger.info("Enriched %s deans; %s not found; %s errors",
                len(report["updated"]), len(report["not_found"]), len(report["errors"]))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["updated"] and not args.dry_run:
        logger.info("Rebuild the typed graph: python -m app.graph.build_typed_graph")


if __name__ == "__main__":
    main()
