"""
v3 P1 — canonical URL registry.

The authoritative entity → verified-KB-URL map. Citations and entity/graph
contexts use these URLs; they are NEVER reconstructed from entity names or slugs.

* ``canonical_url_set()`` — process-cached set of normalized verified URLs (also
  fed into the citation scrubber). Cheap: loaded once, refreshed on a TTL, so it
  does not add per-answer Supabase reads (P5 egress).
* ``rebuild_canonical_urls(db)`` — (re)populate the table from the entity tables
  and curated FAQ source URLs.
"""

from __future__ import annotations

import logging
import time

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.rag.citation_validator import _norm_url

logger = logging.getLogger(__name__)

_CACHE: dict[str, object] = {"urls": frozenset(), "loaded_at": 0.0}
_TTL_SECONDS = 600.0


def canonical_url_set() -> frozenset[str]:
    """Normalized canonical URLs, cached in-process for ``_TTL_SECONDS``."""
    now = time.time()
    if _CACHE["urls"] and (now - float(_CACHE["loaded_at"])) < _TTL_SECONDS:
        return _CACHE["urls"]  # type: ignore[return-value]
    try:
        from app.db.database import get_session_local
        from app.db.models import CanonicalURL

        db = get_session_local()()
        try:
            urls = frozenset(
                _norm_url(u) for (u,) in db.query(CanonicalURL.canonical_url).all() if u
            )
        finally:
            db.close()
        _CACHE["urls"] = urls
        _CACHE["loaded_at"] = now
        return urls
    except OperationalError:
        return _CACHE["urls"]  # type: ignore[return-value]
    except Exception as exc:
        logger.debug("canonical_url_set load skipped: %s", exc)
        return _CACHE["urls"]  # type: ignore[return-value]


def peek_canonical_url_set() -> frozenset[str]:
    """Return the in-process cache WITHOUT triggering a DB load. Used on the hot
    per-answer path so citation validation never adds a Supabase read (P5 egress);
    the cache is warmed at startup via ``canonical_url_set()``."""
    return _CACHE["urls"]  # type: ignore[return-value]


def invalidate_cache() -> None:
    _CACHE["urls"] = frozenset()
    _CACHE["loaded_at"] = 0.0


def rebuild_canonical_urls(db: Session) -> dict:
    """(Re)populate canonical_urls from entity tables + curated FAQ source URLs."""
    from app.db.models import (
        CanonicalURL,
        UMBCampus,
        UMBContact,
        UMBFAQ,
        UMBFaculty,
        UMBScholarship,
        UMBService,
        UMBStudyProgram,
    )

    rows: list[tuple[str, str, str]] = []  # (entity_type, entity_name, url)
    for f in db.query(UMBFaculty).all():
        if f.website_url:
            rows.append(("faculty", f.name, f.website_url))
    for p in db.query(UMBStudyProgram).all():
        if p.website_url:
            rows.append(("study_program", p.program_name, p.website_url))
    for c in db.query(UMBCampus).all():
        if c.website_url:
            rows.append(("campus", c.campus_name, c.website_url))
    for s in db.query(UMBScholarship).all():
        for u in (s.source_urls or []):
            rows.append(("scholarship", s.scholarship_name, u))
    for c in db.query(UMBContact).all():
        if c.url:
            rows.append(("contact", c.office_name, c.url))
    for s in db.query(UMBService).all():
        if s.url:
            rows.append(("service", s.service_name, s.url))
    for faq in db.query(UMBFAQ).all():
        for u in (faq.source_urls or []):
            rows.append(("faq", (faq.category or "faq"), u))

    existing = {
        (et, en, _norm_url(u))
        for (et, en, u) in db.query(CanonicalURL.entity_type, CanonicalURL.entity_name, CanonicalURL.canonical_url).all()
    }
    inserted = 0
    for et, en, url in rows:
        key = (et, en, _norm_url(url))
        if key in existing:
            continue
        existing.add(key)
        db.add(CanonicalURL(entity_type=et, entity_name=en, canonical_url=url))
        inserted += 1
    db.commit()
    invalidate_cache()
    return {"inserted": inserted, "total_candidates": len(rows)}


def main() -> None:
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(message)s")
    from app.db.database import get_engine, get_session_local
    from app.db.models import Base

    try:
        Base.metadata.create_all(get_engine(), checkfirst=True)
    except Exception as exc:
        logger.warning("create_all skipped: %s", exc)
    db = get_session_local()()
    try:
        result = rebuild_canonical_urls(db)
    finally:
        db.close()
    logger.info("canonical_urls rebuilt: %s", result)


if __name__ == "__main__":
    main()
