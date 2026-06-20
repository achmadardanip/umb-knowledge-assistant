"""Phase 20 P20.4 — conversation recovery via clarification.

When a follow-up is ambiguous (an attribute question like "siapa dekannya?" with
no resolvable subject and no session memory, or several equally-ranked entities),
instead of answering "Saya tidak menemukan jawaban." we ask the user to choose:

    Apakah yang Anda maksud:
      1. Dekan FEB
      2. Dekan FASILKOM
      3. Dekan FIKOM

Options are built ONLY from real entity rows, so the clarification never invents
a faculty/program — no hallucination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chat.session_memory import SessionContext, _match_faculty, _match_program

# Attribute the user is asking about, when the subject is omitted.
_ATTR_PATTERNS = {
    "dean": (r"\bdekan", "Dekan"),
    "kaprodi": (r"\bkaprodi|ketua program studi|kepala program studi", "Kaprodi"),
    "accreditation": (r"\bakreditas", "Akreditasi"),
}


@dataclass
class ClarificationResult:
    needs_clarification: bool
    attribute: str | None
    message: str | None
    options: list[str]


def _detected_attribute(query: str) -> tuple[str, str] | None:
    low = (query or "").lower()
    for key, (pat, label) in _ATTR_PATTERNS.items():
        if re.search(pat, low):
            return key, label
    return None


def clarify(
    db: Session,
    query: str,
    contexts: list[dict] | None,
    session_ctx: SessionContext | None = None,
    *,
    max_options: int = 6,
) -> ClarificationResult:
    """Decide whether to ask a clarifying question. Triggers only when the query
    asks for an attribute (dean/kaprodi/accreditation), the subject is omitted
    (no explicit faculty/program in the query, nothing in session memory) and
    retrieval did not produce a confident single entity."""
    attr = _detected_attribute(query)
    if not attr:
        return ClarificationResult(False, None, None, [])
    key, label = attr

    # subject present? -> no clarification needed.
    if _match_faculty(query) or _match_program(query):
        return ClarificationResult(False, key, None, [])
    if session_ctx and (session_ctx.faculty or session_ctx.program):
        return ClarificationResult(False, key, None, [])

    # confident single entity already retrieved? -> answerable, no clarification.
    top = (contexts or [{}])[0] if contexts else {}
    if top and float(top.get("score") or 0) >= 9.0 and top.get("entity_type") in {"faculty", "study_program"}:
        return ClarificationResult(False, key, None, [])

    # Ambiguous: build real options.
    options: list[str] = []
    try:
        if key in {"dean"}:
            rows = db.execute(text("SELECT name_short, name FROM umb_faculties WHERE dean IS NOT NULL ORDER BY name_short")).all()
            options = [f"{label} {r[0]}" for r in rows]
        else:  # kaprodi / accreditation -> programs
            rows = db.execute(text("SELECT program_name FROM umb_study_programs ORDER BY program_name")).all()
            seen, names = set(), []
            for (pn,) in rows:
                if pn not in seen:
                    seen.add(pn)
                    names.append(pn)
            options = [f"{label} {n}" for n in names]
    except Exception:
        options = []

    options = options[:max_options]
    if not options:
        return ClarificationResult(False, key, None, [])
    numbered = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))
    message = f"Pertanyaan Anda kurang spesifik. Apakah yang Anda maksud:\n{numbered}"
    return ClarificationResult(True, key, message, options)
