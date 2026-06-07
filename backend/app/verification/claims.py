"""Atomic-claim decomposition for Corroboration-Gated Claim Verification (CGCV).

An answer is split into atomic claims, each carrying the ``[n]`` citation
markers it references and a marker-free text suitable as an NLI hypothesis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[(\d+)\]")
# Split on sentence-ending punctuation only when followed by whitespace, so
# Indonesian thousands separators ("Rp500.000") are not treated as boundaries.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Claim:
    """A single atomic claim and the citation ids it references."""

    text: str
    citation_ids: tuple[int, ...]


def _clean_text(raw: str) -> str:
    without_markers = _CITATION_RE.sub("", raw)
    collapsed = re.sub(r"\s+", " ", without_markers).strip()
    # Remove whitespace left dangling before punctuation after marker removal.
    return re.sub(r"\s+([.!?,;:])", r"\1", collapsed)


def extract_claims(answer: str) -> list[Claim]:
    text = (answer or "").strip()
    if not text:
        return []
    claims: list[Claim] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            sentence = sentence.strip()
            if not sentence:
                continue
            citation_ids = tuple(int(marker) for marker in _CITATION_RE.findall(sentence))
            cleaned = _clean_text(sentence)
            if cleaned:
                claims.append(Claim(text=cleaned, citation_ids=citation_ids))
    return claims
