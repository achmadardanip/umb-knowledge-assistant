"""
Phase 2 — Structured Entity Retriever.

Performs fast, deterministic lookups against the umb_* entity tables before
the hybrid vector search.  Returns formatted context dicts (same shape as
HybridRetriever results) so the downstream CGCV/answer generator can cite them.

Scores are intentionally higher than typical TAHF scores (~1-2) so entity
contexts rank first when they match.  If the tables don't exist (e.g. migration
not yet applied) the function returns [] silently.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Score assigned to seeded entities (confidence ≥ 0.8) — above normal TAHF max.
_ENTITY_SCORE_HIGH = 10.0
# Score for mined / lower-confidence entities.
_ENTITY_SCORE_LOW = 7.0
# UMB root hostname used for context dicts when entity has no website URL.
_DEFAULT_HOST = "www.mercubuana.ac.id"
_DEFAULT_URL = "https://www.mercubuana.ac.id/"

# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------

_FACULTY_TERMS = {
    "fakultas", "faculty", "faculties", "feb", "ft", "fasilkom",
    "fikom", "fdsk", "fpsi", "pasca", "pascasarjana",
    "dekan", "dean", "akreditasi", "accreditation",
    "ekonomi", "teknik", "komputer", "komunikasi", "desain", "psikologi",
}
_PROGRAM_TERMS = {
    "program", "program studi", "prodi", "jurusan", "degree",
    "akreditasi", "accreditation",
    "informatika", "informasi", "manajemen", "akuntansi", "elektro",
    "mesin", "sipil", "industri", "arsitektur", "penyiaran", "periklanan",
    "humas", "hubungan masyarakat", "dkv", "desain komunikasi", "psikologi",
}
_CAMPUS_TERMS = {
    "kampus", "campus", "lokasi", "location", "alamat", "address",
    "meruya", "menteng", "warung buncit", "bekasi", "gedung", "building",
}
_SCHOLARSHIP_TERMS = {
    "beasiswa", "scholarship", "kip", "ppa",
}
_CONTACT_TERMS = {
    "kontak", "contact", "hubungi", "telepon", "phone", "email",
    "pmb", "baa", "bti", "ditmawa", "kemahasiswaan", "perpustakaan",
    "pendaftaran", "admission", "registrasi", "whatsapp", "nomor",
    "daftar", "mendaftar", "mendaftarkan", "mahasiswa baru",
}
_SERVICE_TERMS = {
    "sia", "sso", "login", "masuk", "elearning", "e-learning",
    "repository", "layanan", "service", "portal",
}


def _tokenize(query: str) -> list[str]:
    return [t.lower().strip() for t in re.findall(r"[\w\-]+", query or "") if len(t) > 1]


def _has_any(tokens: list[str], terms: set[str]) -> bool:
    for tok in tokens:
        if tok in terms:
            return True
        for term in terms:
            if " " in term and term in " ".join(tokens):
                return True
    return False


def _entity_score(confidence: float | None) -> float:
    conf = float(confidence or 0.5)
    return _ENTITY_SCORE_HIGH if conf >= 0.8 else _ENTITY_SCORE_LOW


# Specific study-program keywords → canonical program name. A token here means
# the query is program-level (e.g. "akreditasi sistem informasi"), so program
# entities must outrank faculty entities on a score tie. (Phase 14 P2.)
# NB: bare "informasi" is intentionally NOT a key — it is a very common word
# ("information") and used to mis-trigger the Sistem Informasi program. The
# "Sistem Informasi" program is matched by the phrase lookup in _lookup_programs.
_PROGRAM_NAME_MAP = {
    "informatika": "Teknik Informatika",
    "manajemen": "Manajemen",
    "akuntansi": "Akuntansi",
    "elektro": "Teknik Elektro",
    "mesin": "Teknik Mesin",
    "sipil": "Teknik Sipil",
    "industri": "Teknik Industri",
    "arsitektur": "Arsitektur",
    "penyiaran": "Penyiaran",
    "periklanan": "Periklanan",
    "humas": "Hubungan Masyarakat",
    "dkv": "Desain Komunikasi Visual",
    "psikologi": "Psikologi",
}

# Deterministic tie-break priority (lower = higher priority) used when several
# entity contexts share the same score. Program-level queries should resolve to
# the program, not an incidentally-matched faculty. (Phase 14 P2.)
_TYPE_PRIORITY = {
    "study_program": 0,
    "faculty": 1,
    "person": 2,
    "campus": 3,
    "scholarship": 3,
    "contact": 3,
    "service": 3,
}


def _program_specific(tokens: list[str]) -> bool:
    return any(t in _PROGRAM_NAME_MAP for t in tokens)


# ---------------------------------------------------------------------------
# Per-entity-type formatters → context dicts
# ---------------------------------------------------------------------------


def _faculty_context(f) -> dict:
    parts = [f"Fakultas: {f.name}"]
    if f.name_short:
        parts.append(f"Nama singkat: {f.name_short}")
    if f.dean:
        parts.append(f"Dekan: {f.dean}")
    if f.accreditation_grade:
        body = f" ({f.accreditation_body})" if f.accreditation_body else ""
        parts.append(f"Akreditasi: {f.accreditation_grade}{body}")
    if f.campus:
        parts.append(f"Kampus: {f.campus}")
    if f.contact_phone:
        parts.append(f"Telepon: {f.contact_phone}")
    if f.contact_email:
        parts.append(f"Email: {f.contact_email}")
    if f.website_url:
        parts.append(f"Website: {f.website_url}")
    url = f.website_url or _DEFAULT_URL
    hostname = url.split("/")[2] if "://" in url else _DEFAULT_HOST
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": f.name,
        "score": _entity_score(f.confidence),
        "hostname": hostname,
        "entity_type": "faculty",
        "entity_id": str(f.id),
        "confidence": float(f.confidence or 0.5),
        "source_type": "entity",
    }


def _program_context(p) -> dict:
    parts = [f"Program Studi: {p.program_name} ({p.degree_level or 'S1'})"]
    if p.faculty_name:
        parts.append(f"Fakultas: {p.faculty_name}")
    if p.head_of_program:
        parts.append(f"Ketua Program Studi: {p.head_of_program}")
    if p.accreditation_grade:
        body = f" ({p.accreditation_body})" if p.accreditation_body else ""
        parts.append(f"Akreditasi: {p.accreditation_grade}{body}")
    if p.campus:
        parts.append(f"Kampus: {p.campus}")
    if p.website_url:
        parts.append(f"Website: {p.website_url}")
    url = p.website_url or (p.faculty and p.faculty.website_url) or _DEFAULT_URL
    hostname = url.split("/")[2] if "://" in url else _DEFAULT_HOST
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": f"{p.program_name} — {p.faculty_name or 'UMB'}",
        "score": _entity_score(p.confidence),
        "hostname": hostname,
        "entity_type": "study_program",
        "entity_id": str(p.id),
        "confidence": float(p.confidence or 0.5),
        "source_type": "entity",
    }


def _campus_context(c) -> dict:
    parts = [f"Kampus: {c.campus_name}"]
    if c.address:
        parts.append(f"Alamat: {c.address}")
    if c.city:
        parts.append(f"Kota: {c.city}")
    if c.phone:
        parts.append(f"Telepon: {c.phone}")
    if c.fax:
        parts.append(f"Faks: {c.fax}")
    if c.facilities:
        facs = ", ".join(c.facilities) if isinstance(c.facilities, list) else str(c.facilities)
        if facs:
            parts.append(f"Fasilitas: {facs}")
    url = c.website_url or _DEFAULT_URL
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": f"Kampus {c.campus_name} — Universitas Mercu Buana",
        "score": _entity_score(c.confidence),
        "hostname": _DEFAULT_HOST,
        "entity_type": "campus",
        "entity_id": str(c.id),
        "confidence": float(c.confidence or 0.5),
        "source_type": "entity",
    }


def _scholarship_context(s) -> dict:
    parts = [f"Beasiswa: {s.scholarship_name}"]
    if s.provider:
        parts.append(f"Penyelenggara: {s.provider}")
    if s.description:
        parts.append(s.description)
    if s.eligibility:
        parts.append(f"Syarat: {s.eligibility}")
    if s.requirements:
        parts.append(f"Ketentuan: {s.requirements}")
    if s.amount:
        parts.append(f"Besaran: {s.amount}")
    if s.deadline:
        parts.append(f"Deadline: {s.deadline}")
    if s.contact:
        parts.append(f"Kontak: {s.contact}")
    src_urls: list = s.source_urls or []
    url = src_urls[0] if src_urls else _DEFAULT_URL
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": s.scholarship_name,
        "score": _entity_score(s.confidence),
        "hostname": _DEFAULT_HOST,
        "entity_type": "scholarship",
        "entity_id": str(s.id),
        "confidence": float(s.confidence or 0.5),
        "source_type": "entity",
    }


def _contact_context(c) -> dict:
    parts = [f"Kantor/Unit: {c.office_name}"]
    if c.unit:
        parts.append(f"Unit: {c.unit}")
    if c.phone:
        parts.append(f"Telepon: {c.phone}")
    if c.whatsapp:
        parts.append(f"WhatsApp: {c.whatsapp}")
    if c.email:
        parts.append(f"Email: {c.email}")
    if c.location:
        parts.append(f"Lokasi: {c.location}")
    if c.campus:
        parts.append(f"Kampus: {c.campus}")
    if c.service_hours:
        parts.append(f"Jam Layanan: {c.service_hours}")
    url = c.url or _DEFAULT_URL
    hostname = url.split("/")[2] if "://" in url else _DEFAULT_HOST
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": c.office_name,
        "score": _entity_score(c.confidence),
        "hostname": hostname,
        "entity_type": "contact",
        "entity_id": str(c.id),
        "confidence": float(c.confidence or 0.5),
        "source_type": "entity",
    }


def _service_context(s) -> dict:
    parts = [f"Layanan: {s.service_name}"]
    if s.description:
        parts.append(s.description)
    if s.unit:
        parts.append(f"Unit: {s.unit}")
    if s.url:
        parts.append(f"URL: {s.url}")
    url = s.url or _DEFAULT_URL
    hostname = url.split("/")[2] if "://" in url else _DEFAULT_HOST
    return {
        "chunk_text": ". ".join(parts) + ".",
        "url": url,
        "title": s.service_name,
        "score": _entity_score(s.confidence),
        "hostname": hostname,
        "entity_type": "service",
        "entity_id": str(s.id),
        "confidence": float(s.confidence or 0.5),
        "source_type": "entity",
    }


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _lookup_faculties(db: Session, tokens: list[str], suppress_generic: bool = False) -> list[dict]:
    from app.db.models import UMBFaculty

    # If a specific faculty name or abbreviation is mentioned, target it
    ABBREV_MAP = {
        "feb": "Fakultas Ekonomi dan Bisnis",
        "ft": "Fakultas Teknik",
        "fasilkom": "Fakultas Ilmu Komputer",
        "fikom": "Fakultas Ilmu Komunikasi",
        "fdsk": "Fakultas Desain dan Seni Kreatif",
        "fpsi": "Fakultas Psikologi",
        "pasca": "Pascasarjana",
        "pascasarjana": "Pascasarjana",
        "teknik": "Fakultas Teknik",
        "ekonomi": "Fakultas Ekonomi dan Bisnis",
        "bisnis": "Fakultas Ekonomi dan Bisnis",
        "komputer": "Fakultas Ilmu Komputer",
        "informatika": "Fakultas Ilmu Komputer",
        "komunikasi": "Fakultas Ilmu Komunikasi",
        "desain": "Fakultas Desain dan Seni Kreatif",
        "psikologi": "Fakultas Psikologi",
    }
    targeted_names = {ABBREV_MAP[t] for t in tokens if t in ABBREV_MAP}

    results: list = []
    if targeted_names:
        for name in targeted_names:
            row = db.query(UMBFaculty).filter(UMBFaculty.name.ilike(f"%{name.split()[-1]}%")).first()
            if row:
                results.append(row)
    elif suppress_generic:
        # Program-level query (a specific program keyword is present): a dump of
        # every faculty is pure noise and used to tie at score 10.0 with the real
        # program entity, letting an unrelated faculty win the tie-break. Skip it.
        results = []
    else:
        # General faculty query — return all faculties
        results = db.query(UMBFaculty).order_by(UMBFaculty.name).limit(8).all()

    return [_faculty_context(f) for f in results if f]


def _lookup_programs(db: Session, tokens: list[str], query_lc: str = "") -> list[dict]:
    from app.db.models import UMBStudyProgram

    # (a) Single-word keyword triggers (e.g. "informatika", "manajemen").
    targeted = {_PROGRAM_NAME_MAP[t] for t in tokens if t in _PROGRAM_NAME_MAP}

    rows: list = []
    seen: set[str] = set()

    # (b) Direct phrase match against the real program names so multi-word
    # programs resolve too — "Desain Komunikasi Visual", "Hubungan Masyarakat",
    # "Ilmu Komunikasi", "Sistem Informasi", "Teknik Elektro", …. This is the
    # precise signal; a generic browse ("program apa saja") matches no single
    # name and so still yields [] (the typed-graph / FAQ layers answer that).
    if query_lc:
        for p in db.query(UMBStudyProgram).all():
            nm = (p.program_name or "").lower().strip()
            if len(nm) >= 4 and nm in query_lc and p.id not in seen:
                seen.add(p.id)
                rows.append(p)

    for name in targeted:
        for p in db.query(UMBStudyProgram).filter(UMBStudyProgram.program_name.ilike(f"%{name}%")).all():
            if p.id not in seen:
                seen.add(p.id)
                rows.append(p)

    return [_program_context(p) for p in rows]


def _lookup_campuses(db: Session, tokens: list[str]) -> list[dict]:
    from app.db.models import UMBCampus

    CAMPUS_KEYWORDS = {
        "meruya": "Meruya",
        "menteng": "Menteng",
        "warung": "Warung Buncit",
        "buncit": "Warung Buncit",
        "bekasi": "Bekasi",
    }
    targeted = {CAMPUS_KEYWORDS[t] for t in tokens if t in CAMPUS_KEYWORDS}

    rows: list = []
    if targeted:
        for name in targeted:
            row = db.query(UMBCampus).filter(UMBCampus.campus_name == name).first()
            if row:
                rows.append(row)
    else:
        rows = db.query(UMBCampus).order_by(UMBCampus.campus_name).all()

    return [_campus_context(c) for c in rows]


def _lookup_scholarships(db: Session, tokens: list[str]) -> list[dict]:
    from app.db.models import UMBScholarship

    SCHOLARSHIP_KEYWORDS = {
        "kip": "KIP",
        "ppa": "PPA",
        "prestasi": "Prestasi",
        "yayasan": "Yayasan",
    }
    targeted = {SCHOLARSHIP_KEYWORDS[t] for t in tokens if t in SCHOLARSHIP_KEYWORDS}

    rows: list = []
    if targeted:
        for kw in targeted:
            found = (
                db.query(UMBScholarship)
                .filter(UMBScholarship.scholarship_name.ilike(f"%{kw}%"))
                .all()
            )
            rows.extend(found)
    else:
        rows = db.query(UMBScholarship).order_by(UMBScholarship.scholarship_name).all()

    seen: set[str] = set()
    results = []
    for s in rows:
        if s.id not in seen:
            seen.add(s.id)
            results.append(_scholarship_context(s))
    return results


def _lookup_contacts(db: Session, tokens: list[str]) -> list[dict]:
    from app.db.models import UMBContact

    SERVICE_TYPE_MAP = {
        "pmb": "admission",
        "pendaftaran": "admission",
        "admission": "admission",
        "daftar": "admission",
        "mendaftar": "admission",
        "registrasi": "admission",
        "baa": "academic",
        "akademik": "academic",
        "sia": "sia",
        "sso": "sso",
        "bti": "technical_support",
        "support": "technical_support",
        "perpustakaan": "library",
        "library": "library",
        "ditmawa": "student_affairs",
        "kemahasiswaan": "student_affairs",
    }
    targeted_types = {SERVICE_TYPE_MAP[t] for t in tokens if t in SERVICE_TYPE_MAP}

    rows: list = []
    if targeted_types:
        rows = (
            db.query(UMBContact)
            .filter(UMBContact.service_type.in_(list(targeted_types)))
            .order_by(UMBContact.office_name)
            .all()
        )
    else:
        rows = db.query(UMBContact).order_by(UMBContact.office_name).limit(5).all()

    return [_contact_context(c) for c in rows]


def _lookup_services(db: Session, tokens: list[str]) -> list[dict]:
    from app.db.models import UMBService

    CATEGORY_MAP = {
        "sia": "academic",
        "sso": "authentication",
        "login": "authentication",
        "elearning": "academic",
        "repository": "library",
        "perpustakaan": "library",
        "pendaftaran": "admission",
    }
    targeted_cats = {CATEGORY_MAP[t] for t in tokens if t in CATEGORY_MAP}

    rows: list = []
    if targeted_cats:
        rows = (
            db.query(UMBService)
            .filter(UMBService.category.in_(list(targeted_cats)))
            .order_by(UMBService.service_name)
            .all()
        )
    else:
        rows = []

    return [_service_context(s) for s in rows]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def query_entities(db: Session, query: str, root_domain: str = "mercubuana.ac.id") -> list[dict]:
    """Return entity contexts for a user query using deterministic table lookups.

    Returns [] if entity tables don't exist (migration not yet applied) or if
    no entities match.  Score values are set high enough that entity contexts
    rank above normal hybrid-retrieval results when present.
    """
    try:
        # v3 P5: cache entity lookups (deterministic per query) to avoid the
        # several Supabase round-trips per chat.
        from app.core.cache import cache_get, cache_set, make_key

        _ck = make_key("entity", root_domain, " ".join((query or "").lower().split()))
        _cached = cache_get(_ck)
        if _cached is not None:
            return [dict(c) for c in _cached]

        tokens = _tokenize(query)
        results: list[dict] = []
        query_lc = " ".join(tokens)

        # Resolve programs first (keyword + phrase match). A non-empty hit means
        # the query names a specific program, so the generic all-faculties dump
        # is suppressed and the program outranks an incidentally-matched faculty.
        program_hits = _lookup_programs(db, tokens, query_lc)
        program_specific = bool(program_hits) or _program_specific(tokens)

        if _has_any(tokens, _FACULTY_TERMS):
            results.extend(_lookup_faculties(db, tokens, suppress_generic=program_specific))

        if program_hits and (_has_any(tokens, _PROGRAM_TERMS) or _has_any(tokens, _FACULTY_TERMS)):
            results.extend(program_hits)

        if _has_any(tokens, _CAMPUS_TERMS):
            results.extend(_lookup_campuses(db, tokens))

        if _has_any(tokens, _SCHOLARSHIP_TERMS):
            results.extend(_lookup_scholarships(db, tokens))

        if _has_any(tokens, _CONTACT_TERMS):
            results.extend(_lookup_contacts(db, tokens))

        if _has_any(tokens, _SERVICE_TERMS):
            results.extend(_lookup_services(db, tokens))

        # Deduplicate by entity_id and sort by score descending
        seen_ids: set[str] = set()
        deduped: list[dict] = []
        for ctx in results:
            eid = ctx.get("entity_id") or ctx.get("url")
            if eid not in seen_ids:
                seen_ids.add(eid)
                deduped.append(ctx)

        # Intent-aware demotion: if the query's intent is topical (tuition,
        # scholarship, location, …) and an entity matched only incidentally
        # (e.g. a program name inside a tuition question), demote it so it no
        # longer dominates the topical FAQ/vector sources. (v2 over-firing fix.)
        from app.rag.intent_router import apply_entity_intent_compatibility

        apply_entity_intent_compatibility(query, deduped)

        # Query-aware tie-break. On an exact score tie the right entity type
        # depends on the question: "dekan/wakil dekan X" is a *faculty* attribute,
        # "kaprodi/ketua program studi X" is a *program* attribute, and a bare
        # named program ("akreditasi sistem informasi") resolves to the program.
        # Otherwise fall back to the default order. (Phase 14 P2/P3.)
        dekan_q = ("dekan" in tokens) or ("dean" in tokens) or ("wakil dekan" in query_lc)
        kaprodi_q = (
            ("kaprodi" in tokens)
            or ("ketua program studi" in query_lc)
            or ("kepala program studi" in query_lc)
            or ("ketua prodi" in query_lc)
        )
        explicit_faculty = ("fakultas" in tokens) or dekan_q
        explicit_program = (
            kaprodi_q or ("prodi" in tokens) or ("jurusan" in tokens)
            or ("program" in tokens and "studi" in tokens)
        )
        if explicit_program or (program_specific and not explicit_faculty):
            prio = {"study_program": 0, "faculty": 1, "person": 2}
        else:
            prio = {"faculty": 0, "study_program": 1, "person": 2}

        deduped.sort(
            key=lambda c: (
                -float(c.get("score") or 0.0),
                prio.get(c.get("entity_type"), _TYPE_PRIORITY.get(c.get("entity_type"), 4) + 3),
            )
        )

        # Cap at 6 entity contexts to avoid crowding out chunk evidence
        final = deduped[:6]
        cache_set(_ck, [dict(c) for c in final], None)  # cache independent copies
        return final

    except OperationalError as exc:
        # Table doesn't exist yet — migration pending
        logger.debug("Entity tables not available (migration pending?): %s", exc)
        return []
    except Exception as exc:
        logger.warning("Entity lookup failed: %s", exc)
        return []
