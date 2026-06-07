"""Suggested follow-up questions after each answer.

Keyword-intent based (no extra LLM call — keeps responses fast and avoids burning
rate limits), bilingual (ID/EN), with sensible defaults.
"""

from __future__ import annotations

_RULES: list[tuple[tuple[str, ...], dict[str, list[str]]]] = [
    (
        ("daftar", "pendaftaran", "admission", "register", "pmb", "mahasiswa baru"),
        {
            "id": ["Berapa biaya pendaftarannya?", "Apa saja syarat pendaftaran?", "Kapan jadwal/gelombang pendaftaran?"],
            "en": ["How much is the registration fee?", "What are the admission requirements?", "When are the admission waves?"],
        },
    ),
    (
        ("biaya", "ukt", "spp", "fee", "tuition", "pembayaran"),
        {
            "id": ["Apakah ada cicilan biaya kuliah?", "Bagaimana cara pembayarannya?", "Apakah ada potongan/beasiswa?"],
            "en": ["Is there an installment option?", "How do I pay the tuition?", "Are there any scholarships or discounts?"],
        },
    ),
    (
        ("sia", "sso", "login", "masuk", "akun", "password"),
        {
            "id": ["Bagaimana cara reset password SSO?", "Ke mana menghubungi dukungan teknis?", "Apa itu SIA Universitas Mercu Buana?"],
            "en": ["How do I reset my SSO password?", "Who do I contact for technical support?", "What is the UMB SIA system?"],
        },
    ),
    (
        ("beasiswa", "scholarship"),
        {
            "id": ["Apa syarat beasiswanya?", "Kapan batas pendaftaran beasiswa?", "Beasiswa apa saja yang tersedia?"],
            "en": ["What are the scholarship requirements?", "When is the scholarship deadline?", "Which scholarships are available?"],
        },
    ),
    (
        ("perpustakaan", "library", "repository", "digilib"),
        {
            "id": ["Bagaimana cara mengakses repository UMB?", "Berapa jam operasional perpustakaan?", "Bagaimana cara meminjam buku?"],
            "en": ["How do I access the UMB repository?", "What are the library opening hours?", "How do I borrow a book?"],
        },
    ),
    (
        ("program", "prodi", "fakultas", "jurusan", "study"),
        {
            "id": ["Apa saja fakultas di UMB?", "Berapa biaya kuliah per program?", "Bagaimana cara mendaftar program ini?"],
            "en": ["What faculties does UMB have?", "What is the tuition per program?", "How do I apply to this program?"],
        },
    ),
]

_DEFAULTS: dict[str, list[str]] = {
    "id": ["Bagaimana cara daftar mahasiswa baru?", "Berapa biaya kuliah di UMB?", "Di mana informasi resmi UMB?"],
    "en": ["How do I register as a new student?", "What is the tuition at UMB?", "Where is the official UMB information?"],
}


def suggest_followups(question: str, language: str | None = "id", limit: int = 3) -> list[str]:
    lang = "en" if (language or "id").lower().startswith("en") else "id"
    text = (question or "").lower()
    for keywords, by_lang in _RULES:
        if any(keyword in text for keyword in keywords):
            return by_lang.get(lang, by_lang["id"])[:limit]
    return _DEFAULTS[lang][:limit]
