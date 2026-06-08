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
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_capability_question(text: str) -> bool:
    return any(pattern in text for pattern in CAPABILITY_PATTERNS)


def classify_intent(question: str, recent_messages: list[dict] | None = None) -> IntentResult:
    text = _clean(question)
    if not text:
        return IntentResult("smalltalk", 0.5, "Pertanyaan kosong atau hanya spasi.")

    from app.rag.guardrails import is_disallowed_request

    # Single source of truth for unsafe detection: blocks credential-reveal /
    # malicious intent but allows "lupa/reset password" how-to (handled below).
    if is_disallowed_request(question):
        return IntentResult("unsafe_private_data", 0.9, "Mengandung permintaan kredensial, data pribadi, atau akses tidak aman.")

    if any(term in text for term in LOGIN_TERMS):
        return IntentResult("login_help_general", 0.85, "Pertanyaan terkait login/SSO/SIA sehingga hanya panduan publik yang boleh digunakan.")

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

    if any(term in text for term in OFFICIAL_TERMS):
        return IntentResult("official_info_query", 0.8, "Pertanyaan membutuhkan informasi publik resmi UMB.")

    return IntentResult("official_info_query", 0.6, "Default aman: cari sumber resmi UMB sebelum menjawab.")
