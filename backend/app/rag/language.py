from __future__ import annotations

import re


INDONESIAN_MARKERS = {
    "apa",
    "bagaimana",
    "dimana",
    "di",
    "ke",
    "dari",
    "untuk",
    "yang",
    "mahasiswa",
    "pendaftaran",
    "biaya",
    "beasiswa",
    "program",
    "kuliah",
    "universitas",
    "kampus",
    "perpustakaan",
    "saya",
    "tidak",
    "bisa",
}

ENGLISH_MARKERS = {
    "what",
    "how",
    "where",
    "when",
    "why",
    "which",
    "admission",
    "tuition",
    "scholarship",
    "student",
    "study",
    "program",
    "campus",
    "library",
    "university",
    "can",
    "cannot",
}


def detect_language(text: str) -> str:
    """Cheap language detection for routing prompts without an extra LLM call."""

    tokens = [token.lower() for token in re.findall(r"[A-Za-zÀ-ÿ]+", text or "")]
    if not tokens:
        return "auto"
    id_hits = sum(1 for token in tokens if token in INDONESIAN_MARKERS or token.endswith(("nya", "kan")))
    en_hits = sum(1 for token in tokens if token in ENGLISH_MARKERS)
    if id_hits > en_hits:
        return "id"
    if en_hits > id_hits:
        return "en"
    return "auto"


def language_instruction(language: str | None) -> str:
    normalized = (language or "auto").strip().lower()
    if normalized in {"id", "indonesian", "indonesia", "bahasa indonesia"}:
        return "Jawab dalam bahasa Indonesia."
    if normalized in {"en", "english"}:
        return "Answer in English."
    return "Jawab menggunakan bahasa yang sama dengan pertanyaan pengguna jika memungkinkan."
