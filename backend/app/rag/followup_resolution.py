"""Phase 20 P20.2 — conversational follow-up resolution.

Resolves omitted references in elliptical follow-ups against the session entity
memory (P20.1):

    "Beliau menjabat sejak kapan?"  -> + the remembered faculty (its dean)
    "Bagaimana akreditasinya?"       -> + the remembered program/faculty
    "Kalau yang kelas karyawan?"     -> + the remembered program + "kelas karyawan"
    "Yang kampus Meruya?"            -> + the remembered subject + Meruya

The resolver returns an *enrichment hint* (the canonical remembered entity name)
that the contextual-query builder appends, so the structured entity layer resolves
the follow-up to the right card. It never invents an entity — if memory is empty
it returns no enrichment (the normal not-found / clarification path then applies).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chat.session_memory import SessionContext, _match_faculty, _match_program, _match_service

# Anaphora / subject-omitting markers that signal an elliptical follow-up.
_ANAPHORA = (
    "beliau", "dia", "ia", "mereka", "itu", "tersebut", "nya", "yang itu", "yang tadi",
)
# Attribute-only follow-ups (subject omitted): the "-nya" suffix or a bare attribute.
_ELLIPTICAL_ATTR = (
    "dekannya", "kaprodinya", "akreditasinya", "kampusnya", "lokasinya", "alamatnya",
    "profilnya", "websitenya", "kontaknya", "programnya", "jurusannya", "biayanya",
    "akreditasi", "kaprodi", "dekan", "kelas karyawan", "kampus meruya", "kampus menteng",
    # bare location/attribute interrogatives with no named subject (Phase 31 STEP 6):
    # "Di kampus mana?", "Lokasinya di mana?" — these lean on the prior subject just
    # like a "-nya" attribute, and with no memory must be guarded (not silently
    # defaulted). They name no faculty/program/service, so is_elliptical's early
    # self-contained guard does not fire.
    "kampus mana", "lokasinya",
)


@dataclass
class ResolvedFollowup:
    is_elliptical: bool
    resolved_reference: str | None      # the canonical entity injected (or None)
    enrichment_hint: str | None         # text to append to the retrieval query
    reason: str


def _has_marker(low: str, markers) -> bool:
    for m in markers:
        if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", low):
            return True
    return False


def is_elliptical(query: str) -> bool:
    """True when the query omits its subject and leans on an anaphor/attribute, AND
    does not itself name a faculty/program/service (which would be self-contained).
    The Indonesian definite/possessive suffix "-nya" (dekannya, akreditasinya,
    sejarahnya, visi misinya) is a strong elliptical signal."""
    low = (query or "").lower()
    if _match_faculty(low) or _match_program(low) or _match_service(low):
        return False
    if re.search(r"\w{3,}nya\b", low):  # generic "-nya" suffix -> refers to the prior subject
        return True
    return _has_marker(low, _ANAPHORA) or _has_marker(low, _ELLIPTICAL_ATTR)


def resolve_followup(query: str, ctx: SessionContext | None) -> ResolvedFollowup:
    """Resolve an elliptical follow-up against session memory. Returns an enrichment
    hint naming the remembered subject so the entity layer can resolve it."""
    low = (query or "").lower()
    if not is_elliptical(query):
        return ResolvedFollowup(False, None, None, "self_contained")
    if ctx is None:
        return ResolvedFollowup(True, None, None, "no_memory")

    # Pick the most specific remembered subject for this follow-up.
    # A person anaphor ("beliau") or a faculty-level attribute -> faculty;
    # a program-level attribute or a remembered program -> program.
    wants_faculty = ("dekan" in low or "fakultas" in low or "beliau" in low)
    subject = None
    if wants_faculty and ctx.faculty:
        # dean / "beliau" is a faculty-level reference.
        subject = ctx.faculty
    elif ctx.program:
        # a program is the more specific active subject (its own kaprodi /
        # accreditation / kelas karyawan); prefer it within a program thread.
        subject = ctx.program
    else:
        subject = ctx.faculty

    if not subject:
        return ResolvedFollowup(True, None, None, "memory_empty_for_subject")
    return ResolvedFollowup(True, subject, f"Konteks entitas: {subject}", "resolved_from_memory")


def enrich_query(query: str, ctx: SessionContext | None) -> str:
    """Convenience: return the query with the resolved entity appended (or unchanged)."""
    r = resolve_followup(query, ctx)
    if r.enrichment_hint and r.resolved_reference and r.resolved_reference.lower() not in query.lower():
        return f"{query}\n{r.enrichment_hint}"
    return query
