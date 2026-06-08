"""Clarifying-question generation for vague / overly-general / ambiguous queries.

When a question maps to a topic that is inherently ambiguous at UMB (e.g. "biaya
kuliah" without a program/level, "jadwal" without saying which schedule) we return
clarifying questions instead of guessing. The chat layer can then short-circuit
*without calling the LLM* (saving rate-limited quota) and present these as chips.

Two public helpers, sharing one matcher:
  * ``clarifying_questions`` -> the questions to show the user (the AI "asking back").
  * ``clarification_suggestions`` -> concrete, *answerable* example queries to render
    as clickable chips. Each suggestion is specific enough that clicking it will NOT
    re-trigger clarification (asserted in tests).

An empty list means the query is specific enough to answer directly.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_PROGRAM_WORDS: tuple[str, ...] = (
    "teknik", "informatika", "sistem informasi", "manajemen", "akuntansi", "hukum",
    "psikologi", "komunikasi", "sipil", "mesin", "elektro", "industri", "arsitektur",
    "desain", "ekonomi", "kedokteran", "broadcasting", "periklanan", "marketing",
    "fakultas", "prodi", "jurusan", "program studi",
)
_JENJANG_WORDS: tuple[str, ...] = (
    "s1", "s2", "s3", "sarjana", "magister", "doktor", "diploma", "d3",
    "pascasarjana", "master", "bachelor", "undergraduate", "doctorate",
)
_CLASS_WORDS: tuple[str, ...] = (
    "reguler", "karyawan", "kelas malam", "kelas online", "online", "p2k", "employee class",
)

_GENERIC_STOPWORDS: frozenset[str] = frozenset({
    "dong", "kak", "min", "ya", "nih", "tolong", "mohon", "info", "infonya",
    "gimana", "bagaimana", "apa", "apakah", "saya", "aku", "mau", "ingin", "pengen",
    "tentang", "soal", "umb", "mercu", "buana", "universitas", "yang", "di", "ke",
    "dari", "untuk", "ada", "kah", "ini", "itu", "dan", "atau", "berapa", "kapan",
    "how", "what", "the", "is", "a", "an", "about", "tell", "me", "please", "i",
    "want", "to", "of", "at", "do", "you", "can",
})

# (key, triggers, disambiguators, questions_id, questions_en, suggestions_id, suggestions_en)
_TOPICS: list[tuple[str, tuple[str, ...], tuple[str, ...], list[str], list[str], list[str], list[str]]] = [
    (
        "biaya",
        ("biaya", "spp", "ukt", "uang kuliah", "uang pangkal", "bayar kuliah", "tuition", "fee", "cost"),
        _PROGRAM_WORDS + _JENJANG_WORDS + _CLASS_WORDS,
        ["Untuk program studi apa?", "Jenjang S1, S2, atau S3?", "Kelas reguler atau karyawan?"],
        ["Which study program?", "Which level — undergraduate (S1), master (S2), or doctorate (S3)?", "Regular or employee class?"],
        ["Biaya kuliah S1 Teknik Informatika kelas karyawan", "Biaya kuliah S1 Manajemen reguler", "Biaya kuliah S2 Magister Manajemen"],
        ["Tuition for S1 Informatics employee class", "Tuition for S1 Management regular class", "Tuition for the S2 Master of Management"],
    ),
    # NOTE: "pendaftaran" is intentionally NOT a clarification topic — the registration
    # *process* has a useful general answer, so we answer it directly (ChatGPT-like)
    # rather than interrogate. Bare/contentless forms ("mau daftar") still hit the
    # generic clarifier. Only genuinely parameter-dependent topics clarify below.
    (
        "jadwal",
        ("jadwal", "schedule", "kapan"),
        ("kuliah", "ujian", "uas", "uts", "wisuda", "pendaftaran", "krs", "registrasi", "libur",
         "semester", "exam", "graduation", "lecture", "skripsi", "sidang"),
        ["Jadwal apa yang dimaksud — kuliah, ujian, pendaftaran, atau wisuda?"],
        ["Which schedule do you mean — lectures, exams, registration, or graduation?"],
        ["Jadwal ujian UTS dan UAS", "Jadwal wisuda periode terbaru", "Jadwal registrasi KRS semester"],
        ["UTS and UAS exam schedule", "Latest graduation schedule", "KRS registration schedule for the semester"],
    ),
    (
        "beasiswa",
        ("beasiswa", "scholarship"),
        ("kip", "kip-k", "unggulan", "prestasi", "kjmu", "calon", "mahasiswa aktif", "djarum", "ikatan dinas"),
        ["Beasiswa untuk calon mahasiswa baru atau mahasiswa aktif?",
         "Jenis beasiswa apa yang dimaksud (mis. KIP-K, prestasi)?"],
        ["Scholarship for new applicants or active students?",
         "Which scholarship type (e.g. KIP-K, achievement)?"],
        ["Beasiswa KIP-K untuk calon mahasiswa", "Beasiswa prestasi untuk mahasiswa aktif"],
        ["KIP-K scholarship for new applicants", "KIP-K achievement scholarship for active students"],
    ),
]

_GENERIC_ID = ["Boleh perjelas — informasi apa yang Anda butuhkan tentang UMB (mis. pendaftaran, biaya, program studi, atau jadwal)?"]
_GENERIC_EN = ["Could you clarify — what information do you need about UMB (e.g. admissions, fees, study programs, or schedule)?"]
_GENERIC_SUGGESTIONS_ID = [
    "Syarat dan cara pendaftaran mahasiswa baru S1",
    "Biaya kuliah S1 Teknik Informatika reguler",
    "Jadwal akademik semester berjalan",
]
_GENERIC_SUGGESTIONS_EN = [
    "Requirements and steps to register for S1",
    "Tuition for S1 Informatics regular class",
    "Academic schedule for the current semester",
]


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _prep(question: str, recent_messages: list[dict] | None) -> tuple[str, str]:
    text = (question or "").lower().strip()
    context_text = text
    if recent_messages:
        prior = " ".join(
            (m.get("content") or "").lower()
            for m in recent_messages
            if m.get("role") in (None, "user")
        )
        context_text = f"{prior} {text}"
    return text, context_text


def _match_topic(text: str, context_text: str):
    for topic in _TOPICS:
        _key, triggers, disambiguators = topic[0], topic[1], topic[2]
        if _contains_any(text, triggers) and not _contains_any(context_text, disambiguators):
            return topic
    return None


def _is_generic(text: str) -> bool:
    tokens = [t for t in _TOKEN_RE.findall(text) if t not in _GENERIC_STOPWORDS]
    return len(tokens) <= 1


def clarifying_questions(
    question: str,
    *,
    recent_messages: list[dict] | None = None,
    retrieved_count: int = 0,
    language: str = "id",
) -> list[str]:
    """Return clarifying questions for a vague/ambiguous query, else an empty list."""
    text, context_text = _prep(question, recent_messages)
    if not text:
        return []
    is_en = language.lower().startswith("en")
    topic = _match_topic(text, context_text)
    if topic:
        return list(topic[4] if is_en else topic[3])
    if _is_generic(text):
        return list(_GENERIC_EN if is_en else _GENERIC_ID)
    return []


def clarification_suggestions(
    question: str,
    *,
    recent_messages: list[dict] | None = None,
    language: str = "id",
) -> list[str]:
    """Return concrete, answerable example queries (chips) for an ambiguous query."""
    text, context_text = _prep(question, recent_messages)
    if not text:
        return []
    is_en = language.lower().startswith("en")
    topic = _match_topic(text, context_text)
    if topic:
        return list(topic[6] if is_en else topic[5])
    if _is_generic(text):
        return list(_GENERIC_SUGGESTIONS_EN if is_en else _GENERIC_SUGGESTIONS_ID)
    return []
