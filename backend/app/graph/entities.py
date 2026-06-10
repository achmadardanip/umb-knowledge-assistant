"""Deterministic, LLM-free entity extraction for the UMB knowledge graph.

GraphRAG needs entities + relations. To stay off the rate-limited LLM, we extract
entities with a high-precision UMB gazetteer (word-boundary matched, returned in a
canonical form) plus a generic acronym pattern for unknown unit codes (e.g. LPPM),
filtering out generic web/file noise (FAQ, PDF, URL, ...).

Precision is favoured over recall: noisy entities create bad co-occurrence edges.
"""

from __future__ import annotations

import re

# Canonical UMB entities. Matched case-insensitively on word boundaries; the
# canonical spelling here is what gets returned (so "sia"/"Sia"/"SIA" -> "SIA").
_GAZETTEER: tuple[str, ...] = (
    # Services / systems
    "SIA", "SSO", "KRS", "KHS", "PMB", "KIP-K", "UTS", "UAS", "KKP",
    "E-Learning", "Tracer Study", "Perpustakaan", "Repository", "LPPM",
    # Institution
    "Universitas Mercu Buana",
    # Faculties
    "Fakultas Ilmu Komputer", "Fakultas Teknik", "Fakultas Ekonomi dan Bisnis",
    "Fakultas Psikologi", "Fakultas Ilmu Komunikasi", "Fakultas Desain dan Seni Kreatif",
    "Fakultas Teknik Perencanaan dan Desain", "Program Pascasarjana",
    # Programs (S1)
    "Teknik Informatika", "Sistem Informasi", "Teknik Elektro", "Teknik Mesin",
    "Teknik Industri", "Teknik Sipil", "Arsitektur", "Manajemen", "Akuntansi",
    "Psikologi", "Ilmu Komunikasi", "Desain Komunikasi Visual",
    # Programs (S2/S3)
    "Magister Manajemen", "Magister Akuntansi", "Magister Teknik Industri",
    "Magister Ilmu Komunikasi", "Doktor Manajemen",
    # Campuses
    "Meruya", "Menteng", "Warung Buncit", "Jatisampurna", "Bekasi",
    # Academic terms / scholarships
    "Beasiswa Unggulan", "Beasiswa KIP-K", "Beasiswa", "Wisuda", "Skripsi",
    "Tesis", "Disertasi", "Magang", "Yudisium",
)

# Set of canonical gazetteer entities (protected from pruning).
GAZETTEER_SET: frozenset[str] = frozenset(_GAZETTEER)

# Compile once: canonical -> word-boundary, case-insensitive matcher.
_GAZETTEER_MATCHERS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (canonical, re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE))
    for canonical in _GAZETTEER
)

# Generic uppercase acronym (2-6 letters, optional -XYZ suffix), minus generic noise.
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}(?:-[A-Z]{1,3})?\b")
_ACRONYM_STOPLIST: frozenset[str] = frozenset({
    "FAQ", "URL", "PDF", "HTML", "API", "HTTP", "HTTPS", "OK", "WIB", "WITA", "WIT",
    "EN", "ID", "FAQS", "CSV", "XLS", "DOC", "PPT", "JPG", "PNG", "SMA", "SMK", "SMP",
})


def extract_entities(text: str) -> list[str]:
    """Return canonical UMB entities found in ``text``, in first-seen order, deduped."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(entity: str) -> None:
        if entity not in seen:
            seen.add(entity)
            found.append(entity)

    for canonical, matcher in _GAZETTEER_MATCHERS:
        if matcher.search(text):
            _add(canonical)

    for match in _ACRONYM_RE.findall(text):
        if match in _ACRONYM_STOPLIST:
            continue
        _add(match)

    return found
