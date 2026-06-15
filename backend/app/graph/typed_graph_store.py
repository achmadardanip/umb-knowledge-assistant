"""
Phase 4 — Typed University GraphRAG: DB build + JSON persistence + retrieval.

  * ``build_typed_graph_from_db`` reads the Phase-2 entity tables and constructs
    the typed property graph (nodes + typed edges).
  * ``save_typed_graph`` / ``load_typed_graph`` persist to JSON (mtime-cached load)
    so the graph is rebuilt by a scheduled job, not on every request.
  * ``typed_expansion_contexts`` matches the query's entities and walks typed
    relations to synthesise deterministic relational-answer contexts ("Fakultas
    Teknik menaungi program studi: …"), in the retriever context shape so they
    merge with FAQ/entity/vector contexts and flow through generation + citation.
"""

from __future__ import annotations

import json
import logging
import os

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.graph.typed_graph import (
    CAMPUS_HAS_FACILITY,
    FACULTY_HAS_DEAN,
    FACULTY_HAS_PROGRAM,
    NODE_CAMPUS,
    NODE_CONTACT,
    NODE_FACILITY,
    NODE_FACULTY,
    NODE_PERSON,
    NODE_PROGRAM,
    NODE_SCHOLARSHIP,
    NODE_SERVICE,
    PROGRAM_BELONGS_TO_FACULTY,
    PROGRAM_HAS_HEAD,
    SCHOLARSHIP_AVAILABLE_FOR_PROGRAM,
    SERVICE_BELONGS_TO_UNIT,
    TypedGraph,
    node_id,
)

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://www.mercubuana.ac.id/"
_DEFAULT_HOST = "www.mercubuana.ac.id"
# Typed-graph relational contexts rank below direct entity cards (10) but above
# vector chunks — they add cross-entity relations the cards don't carry.
_GRAPH_SCORE = 9.0

# Faculty abbreviation aliases (so "fasilkom"/"FT" match the faculty node).
_FACULTY_ALIASES = {
    "Fakultas Ekonomi dan Bisnis": ["FEB"],
    "Fakultas Teknik": ["FT"],
    "Fakultas Ilmu Komputer": ["FASILKOM", "Fakultas Ilmu Komputer", "Ilmu Komputer"],
    "Fakultas Ilmu Komunikasi": ["FIKOM"],
    "Fakultas Desain dan Seni Kreatif": ["FDSK"],
    "Fakultas Psikologi": ["FPSI"],
    "Pascasarjana": ["Pascasarjana", "Program Pascasarjana", "PASCA"],
}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_typed_graph_from_db(db: Session) -> TypedGraph:
    from app.db.models import (
        UMBCampus,
        UMBContact,
        UMBFaculty,
        UMBScholarship,
        UMBService,
        UMBStudyProgram,
    )

    graph = TypedGraph()

    # Faculties + deans
    for faculty in db.query(UMBFaculty).all():
        aliases = list(_FACULTY_ALIASES.get(faculty.name, []))
        if faculty.name_short:
            aliases.append(faculty.name_short)
        fid = graph.upsert_node(
            NODE_FACULTY,
            faculty.name,
            attrs={
                "name_short": faculty.name_short,
                "dean": faculty.dean,
                "accreditation_grade": faculty.accreditation_grade,
                "campus": faculty.campus,
                "website_url": faculty.website_url,
                "confidence": faculty.confidence,
            },
            aliases=aliases,
        )
        if faculty.dean:
            pid = graph.upsert_node(NODE_PERSON, faculty.dean, attrs={"role": "Dekan", "faculty": faculty.name})
            graph.add_edge(fid, FACULTY_HAS_DEAN, pid)

    # Study programs → faculty (both directions) + head
    for program in db.query(UMBStudyProgram).all():
        label = f"{program.program_name} ({program.degree_level})" if program.degree_level else program.program_name
        aliases = [program.program_name]
        pid = graph.upsert_node(
            NODE_PROGRAM,
            label,
            attrs={
                "program_name": program.program_name,
                "degree_level": program.degree_level,
                "faculty_name": program.faculty_name,
                "head_of_program": program.head_of_program,
                "accreditation_grade": program.accreditation_grade,
                "website_url": program.website_url,
                "confidence": program.confidence,
            },
            aliases=aliases,
        )
        if program.faculty_name:
            fid = node_id(NODE_FACULTY, program.faculty_name)
            if fid in graph.nodes:
                graph.add_edge(fid, FACULTY_HAS_PROGRAM, pid)
                graph.add_edge(pid, PROGRAM_BELONGS_TO_FACULTY, fid)
        if program.head_of_program:
            head_id = graph.upsert_node(
                NODE_PERSON, program.head_of_program, attrs={"role": "Ketua Program Studi", "program": program.program_name}
            )
            graph.add_edge(pid, PROGRAM_HAS_HEAD, head_id)

    # Campuses → facilities
    for campus in db.query(UMBCampus).all():
        cid = graph.upsert_node(
            NODE_CAMPUS,
            campus.campus_name,
            attrs={
                "address": campus.address,
                "city": campus.city,
                "phone": campus.phone,
                "website_url": campus.website_url,
                "confidence": campus.confidence,
            },
        )
        facilities = campus.facilities if isinstance(campus.facilities, list) else []
        for facility in facilities:
            if not facility:
                continue
            facility_label = f"{facility} ({campus.campus_name})"
            facid = graph.upsert_node(NODE_FACILITY, facility_label, attrs={"campus": campus.campus_name}, aliases=[str(facility)])
            graph.add_edge(cid, CAMPUS_HAS_FACILITY, facid)

    # Scholarships → eligible programs
    for scholarship in db.query(UMBScholarship).all():
        sid = graph.upsert_node(
            NODE_SCHOLARSHIP,
            scholarship.scholarship_name,
            attrs={
                "provider": scholarship.provider,
                "eligibility": scholarship.eligibility,
                "description": scholarship.description,
                "source_urls": scholarship.source_urls,
                "confidence": scholarship.confidence,
            },
        )
        programs = scholarship.programs_eligible if isinstance(scholarship.programs_eligible, list) else []
        for prog_name in programs:
            pid = node_id(NODE_PROGRAM, prog_name)
            if pid in graph.nodes:
                graph.add_edge(sid, SCHOLARSHIP_AVAILABLE_FOR_PROGRAM, pid)

    # Services → unit (contact)
    contacts_by_unit: dict[str, UMBContact] = {}
    for contact in db.query(UMBContact).all():
        graph.upsert_node(
            NODE_CONTACT,
            contact.office_name,
            attrs={
                "unit": contact.unit,
                "email": contact.email,
                "phone": contact.phone,
                "whatsapp": contact.whatsapp,
                "url": contact.url,
                "service_type": contact.service_type,
            },
            aliases=[contact.unit] if contact.unit else [],
        )
        if contact.unit:
            contacts_by_unit.setdefault(contact.unit, contact)

    for service in db.query(UMBService).all():
        svc_id = graph.upsert_node(
            NODE_SERVICE,
            service.service_name,
            attrs={"unit": service.unit, "url": service.url, "category": service.category, "description": service.description},
        )
        if service.unit and service.unit in contacts_by_unit:
            unit_contact = contacts_by_unit[service.unit]
            contact_id = node_id(NODE_CONTACT, unit_contact.office_name)
            if contact_id in graph.nodes:
                graph.add_edge(svc_id, SERVICE_BELONGS_TO_UNIT, contact_id)

    return graph


def save_typed_graph(graph: TypedGraph, path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(graph.to_dict(), handle, ensure_ascii=False)
    _CACHE.pop(path, None)


# path -> (mtime, graph)
_CACHE: dict[str, tuple[float, TypedGraph]] = {}


def load_typed_graph(path: str) -> TypedGraph | None:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _CACHE.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, "r", encoding="utf-8") as handle:
            graph = TypedGraph.from_dict(json.load(handle))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load typed graph %s: %s", path, exc)
        return None
    _CACHE[path] = (mtime, graph)
    return graph


# ---------------------------------------------------------------------------
# Retrieval — relational summaries
# ---------------------------------------------------------------------------


def _context(text: str, url: str | None, title: str, *, relation: str, confidence: float) -> dict:
    resolved_url = url or _DEFAULT_URL
    hostname = resolved_url.split("/")[2] if "://" in resolved_url else _DEFAULT_HOST
    return {
        "chunk_text": text,
        "url": resolved_url,
        "title": title,
        "score": _GRAPH_SCORE,
        "hostname": hostname,
        "entity_type": "graph_relation",
        "graph_relation": relation,
        "confidence": float(confidence or 0.7),
        "source_type": "graph",
    }


def _faculty_summary(graph: TypedGraph, faculty) -> dict | None:
    programs = graph.neighbors(faculty.id, FACULTY_HAS_PROGRAM, direction="out")
    deans = graph.neighbors(faculty.id, FACULTY_HAS_DEAN, direction="out")
    if not programs and not deans:
        return None
    parts = [f"{faculty.name}"]
    if faculty.attrs.get("name_short"):
        parts[0] += f" ({faculty.attrs['name_short']})"
    if deans:
        parts.append(f"Dekan: {deans[0].name}.")
    if programs:
        names = sorted({p.attrs.get("program_name") or p.name for p in programs})
        parts.append(f"menaungi {len(names)} program studi: {', '.join(names)}.")
    text = " ".join(parts)
    return _context(
        text,
        faculty.attrs.get("website_url"),
        f"Program studi {faculty.name}",
        relation=FACULTY_HAS_PROGRAM,
        confidence=faculty.attrs.get("confidence", 0.8),
    )


def _program_summary(graph: TypedGraph, program) -> dict | None:
    faculties = graph.neighbors(program.id, PROGRAM_BELONGS_TO_FACULTY, direction="out")
    heads = graph.neighbors(program.id, PROGRAM_HAS_HEAD, direction="out")
    pname = program.attrs.get("program_name") or program.name
    parts = [f"Program studi {pname}"]
    if program.attrs.get("degree_level"):
        parts[0] += f" jenjang {program.attrs['degree_level']}"
    if faculties:
        parts.append(f"berada di {faculties[0].name}.")
    if heads:
        parts.append(f"Ketua Program Studi: {heads[0].name}.")
    if program.attrs.get("accreditation_grade"):
        parts.append(f"Akreditasi: {program.attrs['accreditation_grade']}.")
    if len(parts) == 1:
        return None
    text = " ".join(parts)
    url = program.attrs.get("website_url") or (faculties[0].attrs.get("website_url") if faculties else None)
    return _context(
        text,
        url,
        f"{pname} — fakultas & relasi",
        relation=PROGRAM_BELONGS_TO_FACULTY,
        confidence=program.attrs.get("confidence", 0.8),
    )


def _campus_summary(graph: TypedGraph, campus) -> dict | None:
    facilities = graph.neighbors(campus.id, CAMPUS_HAS_FACILITY, direction="out")
    if not facilities:
        return None
    names = sorted({f.attrs.get("campus") and (f.name.split(" (")[0]) or f.name for f in facilities})
    text = f"Kampus {campus.name} memiliki fasilitas: {', '.join(names)}."
    return _context(
        text,
        campus.attrs.get("website_url"),
        f"Fasilitas Kampus {campus.name}",
        relation=CAMPUS_HAS_FACILITY,
        confidence=campus.attrs.get("confidence", 0.8),
    )


def _scholarship_summary(graph: TypedGraph, scholarship) -> dict | None:
    programs = graph.neighbors(scholarship.id, SCHOLARSHIP_AVAILABLE_FOR_PROGRAM, direction="out")
    if not programs:
        return None
    names = sorted({p.attrs.get("program_name") or p.name for p in programs})
    text = f"Beasiswa {scholarship.name} tersedia untuk program studi: {', '.join(names)}."
    src = scholarship.attrs.get("source_urls") or []
    url = src[0] if isinstance(src, list) and src else None
    return _context(
        text,
        url,
        f"Beasiswa {scholarship.name} — program",
        relation=SCHOLARSHIP_AVAILABLE_FOR_PROGRAM,
        confidence=scholarship.attrs.get("confidence", 0.8),
    )


_SUMMARY_BUILDERS = {
    NODE_FACULTY: _faculty_summary,
    NODE_PROGRAM: _program_summary,
    NODE_CAMPUS: _campus_summary,
    NODE_SCHOLARSHIP: _scholarship_summary,
}


def typed_expansion_contexts(
    query: str,
    graph: TypedGraph,
    *,
    root_domain: str = "mercubuana.ac.id",
    limit: int = 3,
) -> list[dict]:
    """Return deterministic relational-summary contexts for the query's entities."""
    try:
        matched = graph.match_nodes(query, types=set(_SUMMARY_BUILDERS), limit=limit * 2)
        contexts: list[dict] = []
        seen: set[str] = set()
        for node in matched:
            builder = _SUMMARY_BUILDERS.get(node.type)
            if builder is None:
                continue
            ctx = builder(graph, node)
            if ctx and ctx["chunk_text"] not in seen:
                seen.add(ctx["chunk_text"])
                contexts.append(ctx)
            if len(contexts) >= limit:
                break
        # Intent-aware demotion: a graph relation that fired on an incidental
        # entity name in a topical question (tuition, calendar, …) is demoted
        # so it no longer outranks the topical sources. (v2 over-firing fix.)
        from app.rag.intent_router import apply_entity_intent_compatibility

        apply_entity_intent_compatibility(query, contexts)
        return contexts
    except Exception as exc:  # graph is best-effort; never break retrieval
        logger.warning("Typed graph expansion skipped: %s", exc)
        return []


def typed_expansion_from_db(
    db: Session,
    query: str,
    *,
    root_domain: str = "mercubuana.ac.id",
    limit: int = 3,
    path: str | None = None,
) -> list[dict]:
    """Convenience: load the persisted typed graph (or build from DB) then expand."""
    graph: TypedGraph | None = None
    if path:
        graph = load_typed_graph(path)
    if graph is None:
        try:
            graph = build_typed_graph_from_db(db)
        except OperationalError as exc:
            logger.debug("Typed graph DB build skipped (tables missing?): %s", exc)
            return []
    return typed_expansion_contexts(query, graph, root_domain=root_domain, limit=limit)
