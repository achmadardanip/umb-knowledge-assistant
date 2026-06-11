"""Intent-aware retrieval gate: the single source of truth for which sources are
allowed to answer which question.

Built from observed failures: login/password questions answered from repository
thesis pages and Biaya Kuliah; support questions answered from finance text; dean
questions citing PMB/repository pages. Root cause: intent was classified but never
used in retrieval, and "found N contexts" was treated as "answerable".

Three jobs, all keyed on a retrieval intent derived from the shared topic taxonomy
(`app.rag.intent_classifier.classify_topic`):

* ``gate_contexts``        — hard domain/page filters + negative-term rejection +
                             answerability scoring; returns (kept, rejected).
* ``should_trigger_live_fallback`` — "no answerable intent-matched context" replaces
                             "no context" as the live-web trigger condition.
* ``refusal_message``      — safe refusal templates for sensitive intents so the LLM
                             is never asked to improvise from junk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.rag.intent_classifier import classify_topic

_ROOT = "mercubuana.ac.id"

# Single official escalation channel for "we don't have a verified answer" cases.
UMB_ADMIN_WHATSAPP = "https://api.whatsapp.com/send/?phone=628119852020"


def admin_contact_line(language: str | None) -> str:
    if (language or "id").lower().startswith("en"):
        return f"For further help, contact the UMB admin via WhatsApp: {UMB_ADMIN_WHATSAPP}"
    return f"Untuk bantuan lebih lanjut, hubungi admin resmi UMB via WhatsApp: {UMB_ADMIN_WHATSAPP}"


def _subdomain(hostname: str | None) -> str:
    host = (hostname or "").lower().strip()
    if not host.endswith(_ROOT):
        return host or "?"
    prefix = host[: -len(_ROOT)].rstrip(".")
    if prefix in ("", "www"):
        return "@"
    return prefix.split(".")[-1]


def _term_hits(blob: str, terms: tuple[str, ...]) -> int:
    hits = 0
    for term in terms:
        escaped = re.escape(term.strip().lower()).replace(r"\ ", r"\s+")
        if escaped and re.search(rf"(?<!\w){escaped}(?!\w)", blob):
            hits += 1
    return hits


@dataclass(frozen=True)
class IntentProfile:
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    allowed_subdomains: frozenset[str] | None  # None = all in-scope subdomains allowed
    disallowed_subdomains: frozenset[str]
    live_terms: str  # appended to the live web fallback query
    sensitive: bool = False
    refusal_id: str | None = None
    refusal_en: str | None = None
    family: str = ""


PROFILES: dict[str, IntentProfile] = {
    "login_help": IntentProfile(
        positive=(
            "sia", "sim akademik", "sso", "single sign on", "login", "password", "kata sandi",
            "reset", "lupa password", "akun", "support", "helpdesk", "bantuan", "ult", "baa",
            "email", "kontak", "tiket", "aktivasi",
        ),
        negative=(
            "biaya kuliah", "rincian pembayaran", "pendaftaran", "pmb", "repository", "jurnal",
            "artikel", "skripsi", "tesis", "prosiding", "cuaca", "browse by year", "subject",
            "abstrak", "penelitian",
        ),
        allowed_subdomains=frozenset({"@", "sia", "sso", "support", "ult", "baa", "bti"}),
        disallowed_subdomains=frozenset({"repository", "publikasi", "pendaftaran", "pmb", "lib", "digilib"}),
        live_terms="SIA SSO reset password bantuan akun support resmi",
        sensitive=True,
        refusal_id=(
            "Saya belum menemukan panduan resmi publik yang menjelaskan langkah login/reset password "
            "SIA/SSO dari sumber UMB yang terverifikasi. Karena ini berkaitan dengan keamanan akun, "
            "saya tidak akan menebak langkahnya. Silakan hubungi Support Center UMB, ULT, atau BAA "
            "melalui kanal resmi Universitas Mercu Buana."
        ),
        refusal_en=(
            "I could not find a verified public official guide for SIA/SSO login/password reset. "
            "Since this concerns account security, I will not guess the steps. Please contact the "
            "official UMB Support Center, ULT, or BAA."
        ),
    ),
    "support": IntentProfile(
        positive=(
            "support", "dukungan", "bantuan", "helpdesk", "tiket", "ult", "kontak", "layanan",
            "email", "whatsapp", "telepon", "hubungi", "sia", "sso", "sistem",
        ),
        negative=(
            "keuangan", "biaya kuliah", "rincian pembayaran", "pmb", "pendaftaran", "repository",
            "jurnal", "skripsi", "tesis", "perpustakaan", "browse by year", "subject",
        ),
        allowed_subdomains=frozenset({"@", "support", "ult", "baa", "sia", "sso", "bti"}),
        disallowed_subdomains=frozenset({"repository", "publikasi", "lib", "digilib", "pendaftaran", "pmb"}),
        live_terms="support center ULT helpdesk kontak dukungan teknis resmi",
        sensitive=True,
        refusal_id=(
            "Saya belum menemukan detail kontak dukungan teknis yang cukup pada sumber UMB yang "
            "terindeks. Silakan buka halaman Support Center UMB (support.mercubuana.ac.id) atau "
            "kanal ULT resmi Universitas Mercu Buana."
        ),
        refusal_en=(
            "I could not find sufficient verified technical-support contact details in the indexed "
            "UMB sources. Please use the official UMB Support Center (support.mercubuana.ac.id) or ULT."
        ),
    ),
    "faculty": IntentProfile(
        positive=(
            "fasilkom", "fakultas", "ilmu komputer", "dekan", "dekanat", "wakil dekan", "struktural",
            "struktur organisasi", "program studi", "prodi", "kaprodi", "dosen",
        ),
        negative=(
            "biaya kuliah", "rincian pembayaran", "pmb", "pendaftaran", "repository", "jurnal",
            "subject", "opac", "perpustakaan", "browse by year", "skripsi", "tesis",
        ),
        allowed_subdomains=None,  # faculty subdomains vary; rely on disallowed + terms
        disallowed_subdomains=frozenset({"pendaftaran", "pmb", "repository", "publikasi", "lib", "digilib"}),
        live_terms="struktur organisasi dekan fakultas resmi",
        refusal_id=(
            "Saya menemukan halaman resmi terkait struktur fakultas, tetapi konteks yang terindeks "
            "belum memuat jawaban secara eksplisit. Saya tidak akan menebak. Silakan cek halaman "
            "Struktur Organisasi Fasilkom atau hubungi Fakultas Ilmu Komputer."
        ),
        refusal_en=(
            "I found official faculty-structure pages, but the indexed context does not state the "
            "answer explicitly, so I will not guess. Please check the Fasilkom organisational "
            "structure page or contact the Faculty of Computer Science."
        ),
    ),
    "pmb": IntentProfile(
        positive=("pendaftaran", "pmb", "daftar", "calon mahasiswa", "gelombang", "jalur", "admission", "biaya", "syarat"),
        negative=("repository", "jurnal", "skripsi", "tesis", "browse by year", "subject", "opac"),
        allowed_subdomains=frozenset({"@", "pendaftaran", "pmb"}),
        disallowed_subdomains=frozenset({"repository", "publikasi", "lib", "digilib"}),
        live_terms="pendaftaran mahasiswa baru PMB resmi",
        family="admission",
    ),
    "tuition": IntentProfile(
        positive=("biaya", "biaya kuliah", "uang kuliah", "rincian pembayaran", "cicilan", "ukt", "spp", "tuition"),
        negative=("repository", "jurnal", "skripsi", "tesis", "browse by year", "subject"),
        allowed_subdomains=frozenset({"@", "pendaftaran", "pmb"}),
        disallowed_subdomains=frozenset({"repository", "publikasi", "lib", "digilib"}),
        live_terms="biaya kuliah rincian pembayaran resmi",
        family="admission",
    ),
    "repository": IntentProfile(
        positive=("repository", "repositori", "skripsi", "tesis", "jurnal", "publikasi", "unggah", "opac", "koleksi"),
        negative=(),
        allowed_subdomains=frozenset({"@", "repository", "publikasi", "lib", "digilib", "jurnal"}),
        disallowed_subdomains=frozenset(),
        live_terms="repository publikasi resmi",
    ),
    "library": IntentProfile(
        positive=("perpustakaan", "library", "pinjam", "koleksi", "turnitin", "digilib", "opac", "jam operasional"),
        negative=("pmb", "gelombang"),
        allowed_subdomains=frozenset({"@", "lib", "digilib", "repository"}),
        disallowed_subdomains=frozenset({"pendaftaran", "pmb"}),
        live_terms="perpustakaan UMB resmi",
    ),
    "location": IntentProfile(
        positive=("lokasi", "alamat", "kampus", "meruya", "menteng", "warung buncit", "jatisampurna", "bekasi", "peta"),
        negative=("repository", "jurnal", "skripsi", "browse by year", "subject"),
        allowed_subdomains=None,
        disallowed_subdomains=frozenset({"repository", "publikasi", "lib", "digilib"}),
        live_terms="alamat lokasi kampus resmi",
    ),
}

_SUPPORT_TRIGGERS = (
    "dukungan teknis", "bantuan teknis", "technical support", "helpdesk", "support center",
    "kontak teknis", "tiket bantuan", "lapor kendala", "hubungi dukungan", "menghubungi dukungan",
    "ult",
)

_TOPIC_TO_INTENT = {
    "login_help": "login_help",
    "faculty": "faculty",
    "pmb": "pmb",
    "tuition": "tuition",
    "repository": "repository",
    "library": "library",
    "location": "location",
}


def detect_retrieval_intent(question: str) -> str:
    text = (question or "").lower()
    if any(trigger in text for trigger in _SUPPORT_TRIGGERS):
        return "support"
    return _TOPIC_TO_INTENT.get(classify_topic(text), "general")


def _blob(context: dict) -> str:
    return " ".join(
        str(value).lower()
        for value in (context.get("title"), context.get("url"), context.get("chunk_text"))
        if value
    )


def answerability_score(question: str, intent: str, context: dict) -> float:
    """0..1: how plausibly this chunk answers this question for this intent."""
    profile = PROFILES.get(intent)
    blob = _blob(context)
    query_terms = tuple({t for t in re.findall(r"[\w\-]{3,}", (question or "").lower())})
    overlap = _term_hits(blob, query_terms) / max(len(query_terms), 1)
    if profile is None:
        return min(1.0, 0.3 + 0.7 * overlap)
    pos = _term_hits(blob, profile.positive)
    neg = _term_hits(blob, profile.negative)
    pos_norm = min(pos / 3.0, 1.0)
    sub = _subdomain(context.get("hostname") or "")
    host_bonus = 0.2 if (profile.allowed_subdomains is None or sub in profile.allowed_subdomains) else 0.0
    score = 0.45 * pos_norm + 0.35 * overlap + host_bonus - 0.15 * min(neg, 3)
    return max(0.0, min(1.0, score))


def gate_contexts(
    question: str,
    intent: str,
    contexts: list[dict],
    *,
    max_negative_hits: int | None = None,
    min_answerability: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Hard intent filter. Returns (kept, rejected); rejected get ``_reject_reason``."""
    settings = get_settings()
    if not settings.enable_strict_intent_filter:
        return list(contexts), []
    profile = PROFILES.get(intent)
    if profile is None:
        return list(contexts), []
    max_neg = settings.retrieval_max_negative_keyword_hits if max_negative_hits is None else max_negative_hits
    min_ans = settings.retrieval_min_answerability_score if min_answerability is None else min_answerability

    kept: list[dict] = []
    rejected: list[dict] = []

    def _reject(ctx: dict, reason: str) -> None:
        ctx = dict(ctx)
        ctx["_reject_reason"] = reason
        rejected.append(ctx)

    for context in contexts:
        blob = _blob(context)
        sub = _subdomain(context.get("hostname") or "")
        pos = _term_hits(blob, profile.positive)
        neg = _term_hits(blob, profile.negative)
        if sub in profile.disallowed_subdomains and not (pos >= 3 and neg == 0):
            _reject(context, f"disallowed_domain_for_intent:{sub}")
            continue
        if profile.allowed_subdomains is not None and sub not in profile.allowed_subdomains and pos == 0:
            _reject(context, f"off_intent_domain:{sub}")
            continue
        if neg > max_neg and neg > pos:
            _reject(context, f"negative_terms_dominate:{neg}")
            continue
        score = answerability_score(question, intent, context)
        if score < min_ans:
            _reject(context, f"low_answerability:{score:.2f}")
            continue
        context = dict(context)
        context["answerability"] = round(score, 3)
        kept.append(context)
    return kept, rejected


# Procedural/help cues that mark a chunk as a *direct answer* to a sensitive how-to/
# account question — not merely a topical portal page that happens to share keywords.
_ANSWER_PATTERN_TERMS = (
    "lupa password", "reset password", "atur ulang", "ganti password", "langkah", "klik",
    "pilih menu", "silakan hubungi", "hubungi", "helpdesk", "tiket", "ajukan", "formulir",
    "panduan", "cara", "ikuti", "aktivasi akun", "email ke", "whatsapp", "kontak",
)
_HELP_HOSTS = frozenset({"support", "ult", "baa", "bti"})


def has_answer_pattern(intent: str, context: dict) -> bool:
    """Spec #2 'direct answer pattern': a sensitive-intent chunk is only a real answer if
    it carries procedural/help cues or comes from a dedicated help/support host."""
    profile = PROFILES.get(intent)
    if profile is None or not profile.sensitive:
        return True
    if _subdomain(context.get("hostname") or "") in _HELP_HOSTS:
        return True
    return _term_hits(_blob(context), _ANSWER_PATTERN_TERMS) >= 1


def should_trigger_live_fallback(intent: str, kept_contexts: list[dict]) -> tuple[bool, str | None]:
    """Live fallback fires on 'no answerable intent-matched contexts', not 'no contexts'."""
    if not kept_contexts:
        return True, "no_intent_matched_contexts"
    profile = PROFILES.get(intent)
    if profile is None:
        return False, None
    settings = get_settings()
    best = max(float(c.get("answerability") or 0.0) for c in kept_contexts)
    bar = settings.retrieval_min_answerability_score
    # Sensitive intents (login/SSO, support) must have a *strong* match before we skip
    # the live web search — a page that merely lives on the right subdomain isn't a real
    # answer. Honours "try Tavily first; only refuse if it finds nothing".
    if profile.sensitive:
        bar = max(bar, 0.55)
        # ...and it must actually look like a help/answer page, not just a login portal
        # that shares keywords. No such page -> go to the live web search.
        if not any(has_answer_pattern(intent, c) for c in kept_contexts):
            return True, "no_direct_answer_pattern"
    if best < bar:
        return True, f"low_answerability:{best:.2f}"
    return False, None


def live_query_for_intent(question: str, intent: str) -> str:
    profile = PROFILES.get(intent)
    if profile is None:
        return question
    return f"{question} {profile.live_terms}".strip()


def refusal_message(intent: str, language: str | None) -> str | None:
    profile = PROFILES.get(intent)
    if profile is None:
        return None
    is_en = (language or "id").lower().startswith("en")
    message = (profile.refusal_en if is_en else profile.refusal_id) or None
    if message:
        message = f"{message}\n\n{admin_contact_line(language)}"
    return message


def history_conflicts(current_intent: str, history_text: str) -> bool:
    """True when prior conversation context belongs to a different profiled intent.

    Prevents e.g. a 'Informasi Fasilkom UMB' chat title from steering a SIA-login
    query into faculty pages."""
    current = PROFILES.get(current_intent)
    if current is None:
        return False
    other_intent = detect_retrieval_intent(history_text)
    other = PROFILES.get(other_intent)
    if other is None:
        return False
    if other_intent == current_intent:
        return False
    if current.family and current.family == other.family:
        return False
    return True
