from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


IntentName = Literal[
    "official_info_query",
    "follow_up_query",
    "capability_query",
    "smalltalk",
    "unsafe_private_data",
    "login_help_general",
    "out_of_scope",
]


@dataclass(frozen=True)
class IntentResult:
    intent: IntentName
    confidence: float
    reason: str
    topic: str = "general"


SMALLTALK_PATTERNS = {
    "halo",
    "hai",
    "hello",
    "hi",
    "pagi",
    "siang",
    "sore",
    "malam",
    "terima kasih",
    "thanks",
    "makasih",
}

UNSAFE_TERMS = (
    "password",
    "kata sandi",
    "otp",
    "token",
    "api key",
    "secret key",
    "nim saya",
    "data pribadi",
    "ambil data mahasiswa",
    "bypass",
    "bobol",
    "retas",
    "hack",
    "akun orang",
)

LOGIN_TERMS = ("login", "sso", "sia", "akun", "masuk", "lupa password", "reset password")
FOLLOW_UP_TERMS = ("itu", "tersebut", "tadi", "lanjut", "lebih detail", "jelaskan lagi", "bagaimana dengan")
CAPABILITY_PATTERNS = (
    "kamu bisa apa",
    "kamu bisa melakukan apa",
    "apa yang bisa kamu lakukan",
    "apa saja yang bisa kamu lakukan",
    "bisa bantu apa",
    "fitur kamu",
    "kemampuan kamu",
    "what can you do",
    "what are your capabilities",
)
OFFICIAL_TERMS = (
    "umb",
    "mercu buana",
    "universitas",
    "pendaftaran",
    "pmb",
    "biaya",
    "beasiswa",
    "fakultas",
    "program studi",
    "akademik",
    "perpustakaan",
    "repository",
    "kampus",
    "dosen",
    "kalender",
    "lokasi",
    "alamat",
    "location",
    "address",
    "campus",
    "tuition",
    "admission",
    "faculty",
    "lecturer",
    "academic calendar",
    "library",
    "scholarship",
    "rector",
    "rektor",
)
OUT_OF_SCOPE_TERMS = (
    "piala dunia",
    "world cup",
    "liga champions",
    "champions league",
    "premier league",
    "nba",
    "formula 1",
    "harga saham",
    "stock price",
    "cuaca hari ini",
    "weather today",
)

TOPIC_TERMS = {
    "library": ("perpustakaan", "library", "pinjam buku", "turnitin", "digilib"),
    "pmb": ("pendaftaran", "pmb", "daftar mahasiswa", "admission", "register", "gelombang"),
    "tuition": ("biaya kuliah", "uang kuliah", "tuition", "rincian pembayaran"),
    "faculty": ("fakultas", "fasilkom", "dekan", "dosen", "program studi", "faculty", "lecturer"),
    "academic_calendar": ("kalender akademik", "jadwal akademik", "academic calendar"),
    "login_help": ("login", "sso", "sia", "lupa password", "reset password"),
    "repository": ("repository", "repositori", "skripsi", "tesis"),
    "location": ("lokasi kampus", "alamat kampus", "campus location", "meruya", "menteng", "warung buncit"),
    "k3": ("k3", "k3lk", "keselamatan dan kesehatan kerja"),
    "news": ("berita", "kabar kampus", "pengumuman", "event", "news"),
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_capability_question(text: str) -> bool:
    return any(pattern in text for pattern in CAPABILITY_PATTERNS)


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term.strip()).replace(r"\ ", r"\s+")
    return bool(escaped and re.search(rf"(?<!\w){escaped}(?!\w)", text))


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains_term(text, term) for term in terms)


def classify_topic(text: str) -> str:
    cleaned = _clean(text)
    for topic, terms in TOPIC_TERMS.items():
        if _contains_any_term(cleaned, terms):
            return topic
    return "general"


def classify_intent(question: str, recent_messages: list[dict] | None = None) -> IntentResult:
    text = _clean(question)
    if not text:
        return IntentResult("smalltalk", 0.5, "Pertanyaan kosong atau hanya spasi.")

    from app.rag.guardrails import is_disallowed_request

    # Single source of truth for unsafe detection: blocks credential-reveal /
    # malicious intent but allows "lupa/reset password" how-to (handled below).
    if is_disallowed_request(question):
        return IntentResult("unsafe_private_data", 0.9, "Mengandung permintaan kredensial, data pribadi, atau akses tidak aman.")

    if _contains_any_term(text, LOGIN_TERMS):
        return IntentResult(
            "login_help_general",
            0.85,
            "Pertanyaan terkait login/SSO/SIA sehingga hanya panduan publik yang boleh digunakan.",
            "login_help",
        )

    if _is_capability_question(text):
        return IntentResult("capability_query", 0.9, "Pengguna menanyakan kemampuan chatbot, bukan informasi dokumen UMB.")

    token_count = len(text.split())
    if token_count <= 3 and any(pattern == text or pattern in text for pattern in SMALLTALK_PATTERNS):
        return IntentResult("smalltalk", 0.85, "Sapaan atau percakapan ringan.")

    has_history = bool(recent_messages)
    if has_history and any(term in text for term in FOLLOW_UP_TERMS):
        return IntentResult("follow_up_query", 0.75, "Pertanyaan tampak merujuk pada konteks percakapan sebelumnya.")

    if "universitas indonesia" in text or "binus" in text or "telkom university" in text:
        if not any(term in text for term in ("umb", "mercu buana")):
            return IntentResult("out_of_scope", 0.7, "Pertanyaan mengarah ke institusi di luar UMB.")

    if _contains_any_term(text, OUT_OF_SCOPE_TERMS) and not _contains_any_term(text, ("umb", "mercu buana")):
        return IntentResult("out_of_scope", 0.85, "Topik tidak berkaitan dengan informasi publik Universitas Mercu Buana.")

    if _contains_any_term(text, OFFICIAL_TERMS):
        return IntentResult(
            "official_info_query",
            0.8,
            "Pertanyaan membutuhkan informasi publik resmi UMB.",
            classify_topic(text),
        )

    return IntentResult("official_info_query", 0.6, "Default aman: cari sumber resmi UMB sebelum menjawab.", classify_topic(text))
