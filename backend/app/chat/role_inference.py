"""Infer the user's role/audience from natural language (no dropdown needed).

Keyword-based, most-specific rule first (e.g. "anak saya" -> orang_tua wins over
"mau daftar" -> calon_mahasiswa). Returns None for the general public.
"""

from __future__ import annotations

_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("orang_tua", ("anak saya", "anak kami", "orang tua", "orangtua", "wali murid", "putra saya", "putri saya")),
    ("dosen", ("saya dosen", "sebagai dosen", "saya mengajar", "kepegawaian", "saya staf", "tendik")),
    ("alumni", ("alumni", "ijazah saya", "legalisir ijazah", "tracer study", "saya sudah lulus")),
    (
        "mahasiswa",
        ("saya mahasiswa", "krs", "khs", "nilai saya", "jadwal kuliah saya", "sks saya", "semester saya",
         "skripsi saya", "ujian saya", "wisuda saya", "sia saya", "akun sia saya"),
    ),
    (
        "calon_mahasiswa",
        ("calon mahasiswa", "mau daftar", "ingin daftar", "mau kuliah", "ingin kuliah", "lulusan sma",
         "lulusan smk", "jalur masuk", "gelombang pendaftaran", "saya calon"),
    ),
]


def infer_audience(question: str, recent_messages: list[dict] | None = None) -> str | None:
    text = (question or "").lower()
    for audience, keywords in _RULES:
        if any(keyword in text for keyword in keywords):
            return audience
    return None
