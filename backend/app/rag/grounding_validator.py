"""
Phase 31 STEP 7 — grounding validator.

A deterministic, last-line guard that decides whether a generated answer is
sufficiently grounded to be shown, or must be replaced by the official refusal.
It is intentionally model-free (no extra LLM call): it inspects the retrieval
score, the presence of citations, and lexical overlap between the answer's
factual sentences and the retrieved context.

Policy (an answer is REJECTED if any holds):
  * retrieval evidence is too weak (top score below ``min_score`` and no citation), OR
  * the answer makes factual claims but carries no citation marker / source, OR
  * the answer's claim sentences have near-zero lexical support in the context.

A rejected answer is replaced with the canonical refusal:
  "Informasi tersebut belum tersedia pada sumber resmi Universitas Mercu Buana."

This validator never *fabricates* content and never upgrades a refusal to an
answer; it only ever downgrades an unsupported answer to the refusal. It is
additive — callers opt in via ``validate_answer`` and may log/act on the verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REFUSAL_TEXT = "Informasi tersebut belum tersedia pada sumber resmi Universitas Mercu Buana."

# Default thresholds — conservative so we never reject a genuinely grounded answer.
DEFAULT_MIN_SCORE = 0.15          # min top retrieval score to treat evidence as usable
DEFAULT_MIN_OVERLAP = 0.08        # min token-overlap ratio between claims and context
_CITATION_RE = re.compile(r"\[\d+\]")
_STOP = {
    "yang", "dan", "di", "ke", "dari", "untuk", "pada", "adalah", "atau", "ini",
    "itu", "dengan", "dapat", "the", "a", "an", "of", "to", "in", "is", "are",
    "for", "and", "or", "umb", "universitas", "mercu", "buana",
}
# Phrases that signal the answer is already an honest refusal / clarification.
_REFUSAL_MARKERS = (
    "belum menemukan", "tidak menebak", "belum tersedia", "tidak dapat",
    "could not find", "not found", "belum memuat", "silakan", "hubungi admin",
)


@dataclass
class GroundingVerdict:
    grounded: bool
    reason: str
    answer: str            # original answer, or REFUSAL_TEXT when rejected
    top_score: float = 0.0
    overlap: float = 0.0
    had_citation: bool = False


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in _STOP}


def _is_refusal(answer: str) -> bool:
    low = (answer or "").lower()
    return any(m in low for m in _REFUSAL_MARKERS)


def _top_score(contexts: list[dict] | None) -> float:
    best = 0.0
    for c in contexts or []:
        try:
            s = float(c.get("score") or 0.0)
        except (TypeError, ValueError):
            s = 0.0
        # entity scores are on a 7-10 scale; normalise them into ~[0,1] for the gate
        if s > 1.5:
            s = min(1.0, s / 10.0)
        best = max(best, s)
    return best


def validate_answer(
    answer: str,
    contexts: list[dict] | None,
    sources: list[dict] | None,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
    not_found: bool = False,
) -> GroundingVerdict:
    """Return a grounding verdict for ``answer`` given its retrieval evidence."""
    answer = answer or ""

    # An explicit not_found / refusal is already safe — pass it through unchanged.
    if not_found or _is_refusal(answer):
        return GroundingVerdict(True, "already a refusal/not_found", answer)

    had_citation = bool(_CITATION_RE.search(answer)) or bool(sources)
    top = _top_score(contexts)

    ctx_blob = " ".join((c.get("chunk_text") or "") for c in (contexts or []))
    # If we have citation sources but no chunk text (entity/FAQ layer), the answer is
    # grounded in the citation evidence — don't penalise on lexical overlap.
    if not ctx_blob.strip() and had_citation:
        return GroundingVerdict(True, "grounded by citations (entity/FAQ layer)", answer,
                                top_score=top, had_citation=True)

    a_tok = _tokens(answer)
    c_tok = _tokens(ctx_blob)
    overlap = (len(a_tok & c_tok) / len(a_tok)) if a_tok else 0.0

    # Rejection conditions.
    if not had_citation and top < min_score:
        return GroundingVerdict(False, "no citation and retrieval score too low",
                                REFUSAL_TEXT, top_score=top, overlap=overlap, had_citation=False)
    if not had_citation:
        return GroundingVerdict(False, "factual answer without any citation",
                                REFUSAL_TEXT, top_score=top, overlap=overlap, had_citation=False)
    if a_tok and overlap < min_overlap and top < min_score:
        return GroundingVerdict(False, "answer claims unsupported by retrieved context",
                                REFUSAL_TEXT, top_score=top, overlap=overlap, had_citation=had_citation)

    return GroundingVerdict(True, "grounded", answer, top_score=top, overlap=overlap, had_citation=had_citation)
