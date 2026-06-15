"""
Intent routing + entity-intent compatibility (v2 retrieval).

Phase-5 validation isolated the dominant precision bug: the entity layer
over-fires on topical/multi-hop questions that merely *mention* an entity name
(e.g. "biaya kuliah program Akuntansi" → the *Akuntansi* program → the FEB
faculty page at rank-1, displacing the tuition source). 147/186 strict failures
were multi-hop, 146 had an Entity context at rank-1.

The fix: classify the question into a canonical intent, then demote structured
contexts whose entity type is *incompatible* with that intent. A demoted context
is kept (as supporting evidence) but flagged ``intent_demoted`` so the retrieval
merge no longer pins it above the topical FAQ/vector sources.
"""

from __future__ import annotations

import re

# Canonical intents (the 15 university domains).
INTENT_ADMISSIONS = "admissions"
INTENT_TUITION = "tuition"
INTENT_SCHOLARSHIP = "scholarship"
INTENT_ACADEMIC_CALENDAR = "academic_calendar"
INTENT_ACADEMIC_REGULATIONS = "academic_regulations"
INTENT_CAMPUS = "campus"
INTENT_FACULTY = "faculty"
INTENT_STUDY_PROGRAM = "study_program"
INTENT_LECTURER = "lecturer"
INTENT_STUDENT_SERVICES = "student_services"
INTENT_SIA = "sia"
INTENT_SSO = "sso"
INTENT_LIBRARY = "library"
INTENT_RESEARCH = "research"
INTENT_GENERAL = "general"

# Score assigned to an intent-incompatible (incidental) structured context.
# Low enough to drop below the topical FAQ (12-14) and a decent vector match,
# but kept (not removed) so it can still serve as supporting context.
INCIDENTAL_SCORE = 2.0

# intent -> entity types that are the *primary* answer for that intent.
# "graph_relation" is grouped with the entity-centric intents. ``None`` = no
# constraint (generic browse questions like "fakultas apa saja").
INTENT_COMPATIBLE_ENTITY_TYPES: dict[str, set[str] | None] = {
    INTENT_TUITION: set(),                     # tuition has no entity row → demote all
    INTENT_ACADEMIC_CALENDAR: set(),
    INTENT_ACADEMIC_REGULATIONS: set(),
    INTENT_SCHOLARSHIP: {"scholarship", "graph_relation"},
    INTENT_CAMPUS: {"campus", "graph_relation"},
    INTENT_FACULTY: {"faculty", "graph_relation"},
    INTENT_STUDY_PROGRAM: {"study_program", "faculty", "graph_relation"},
    INTENT_LECTURER: {"faculty", "graph_relation"},
    INTENT_ADMISSIONS: {"contact"},
    INTENT_STUDENT_SERVICES: {"contact", "service"},
    INTENT_SIA: {"service", "contact"},
    INTENT_SSO: {"service", "contact"},
    INTENT_LIBRARY: {"service", "contact"},
    INTENT_RESEARCH: {"service"},
    INTENT_GENERAL: None,
}


# FAQ category -> the intents that FAQ category legitimately answers. A matched
# FAQ whose category serves none of the detected intent is demoted (e.g. the
# broad "faculties / program list" FAQ must not answer an *admissions* question).
FAQ_CATEGORY_INTENTS: dict[str, set[str]] = {
    "admissions": {INTENT_ADMISSIONS},
    "tuition": {INTENT_TUITION},
    "scholarship": {INTENT_SCHOLARSHIP},
    "academic_calendar": {INTENT_ACADEMIC_CALENDAR},
    "academic_regulations": {INTENT_ACADEMIC_REGULATIONS},
    "sso": {INTENT_SSO, INTENT_SIA},
    "sia": {INTENT_SIA, INTENT_SSO},
    "student_services": {INTENT_STUDENT_SERVICES},
    "campus_information": {INTENT_CAMPUS, INTENT_LIBRARY},
    "faculties": {INTENT_FACULTY, INTENT_STUDY_PROGRAM, INTENT_LECTURER},
}


def _faq_compatible(faq_category: str | None, intent: str) -> bool:
    """A FAQ is compatible if the detected intent is generic, or the FAQ's
    category serves that intent. Unknown categories are never demoted."""
    if intent == INTENT_GENERAL or not faq_category:
        return True
    served = FAQ_CATEGORY_INTENTS.get(faq_category)
    if served is None:
        return True
    return intent in served


def _has(text: str, *terms: str) -> bool:
    for term in terms:
        escaped = re.escape(term).replace(r"\ ", r"\s+")
        if re.search(rf"(?<!\w){escaped}(?!\w)", text):
            return True
    return False


def detect_intent(query: str) -> str:
    """Classify a question into one canonical intent. Ordered by specificity so a
    topical intent (tuition) wins over an incidental entity mention (a program)."""
    t = re.sub(r"\s+", " ", (query or "").strip().lower())
    if not t:
        return INTENT_GENERAL

    # Topical intents first (these are the ones the entity layer over-fires on).
    if _has(t, "biaya", "uang kuliah", "tuition", "spp", "pembayaran", "rincian pembayaran", "uang pangkal", "angsuran", "fee", "fees", "cost"):
        return INTENT_TUITION
    if _has(t, "beasiswa", "scholarship", "kip", "kip-k", "ppa", "bidikmisi"):
        return INTENT_SCHOLARSHIP
    if _has(t, "kalender akademik", "academic calendar", "jadwal akademik", "kapan mulai kuliah", "kapan uts", "kapan uas", "libur semester"):
        return INTENT_ACADEMIC_CALENDAR
    if _has(t, "peraturan", "regulasi", "tata tertib", "sanksi", "regulation", "akademik peraturan", "drop out", "cuti akademik"):
        return INTENT_ACADEMIC_REGULATIONS
    if _has(t, "lokasi", "alamat", "location", "address", "di mana kampus", "dimana kampus", "peta kampus", "meruya", "menteng", "warung buncit", "bekasi", "kampus mana"):
        return INTENT_CAMPUS
    # System/login intents.
    if _has(t, "sia", "sistem informasi akademik", "krs", "khs"):
        return INTENT_SIA
    if _has(t, "sso", "single sign on", "single sign-on"):
        return INTENT_SSO
    if _has(t, "perpustakaan", "library", "digilib", "pinjam buku", "turnitin"):
        return INTENT_LIBRARY
    if _has(t, "repository", "repositori", "jurnal", "publikasi", "penelitian", "research", "skripsi", "tesis", "proceeding"):
        return INTENT_RESEARCH
    if _has(t, "login", "masuk", "lupa password", "reset password", "akun"):
        return INTENT_SSO
    # Admission / services. ("mendaftar"/"mendaftarkan" listed explicitly because
    # the word-boundary match for "daftar" won't fire inside "mendaftar".)
    if _has(t, "daftar", "mendaftar", "mendaftarkan", "pendaftaran", "pmb", "admission", "register", "registrasi", "penerimaan mahasiswa baru", "jalur masuk", "gelombang", "calon mahasiswa"):
        return INTENT_ADMISSIONS
    if _has(t, "legalisir", "ijazah", "transkrip", "layanan mahasiswa", "student services", "ult", "helpdesk", "wisuda", "yudisium"):
        return INTENT_STUDENT_SERVICES
    # Entity-centric intents (these SHOULD keep their entity at rank-1).
    if _has(t, "dekan", "wakil dekan", "dean", "kaprodi", "ketua program studi", "dosen", "lecturer", "pimpinan", "rektor", "rector", "struktural"):
        return INTENT_LECTURER
    if _has(t, "program studi", "prodi", "jurusan", "study program", "akreditasi"):
        return INTENT_STUDY_PROGRAM
    if _has(t, "fakultas", "faculty", "fasilkom", "feb", "fikom", "fdsk", "pascasarjana"):
        return INTENT_FACULTY
    if _has(t, "kontak", "hubungi", "telepon", "email", "whatsapp", "contact"):
        return INTENT_STUDENT_SERVICES
    return INTENT_GENERAL


# Anaphora / continuation markers that signal a follow-up referring to the
# previous turn rather than introducing a new topic.
_FOLLOWUP_MARKERS = (
    "itu", "tersebut", "tadi", "ini", "nya", "mereka", "beliau",
    "lanjut", "lebih detail", "lebih lanjut", "jelaskan lagi", "jelaskan lebih",
    "bagaimana dengan", "kalau", "terus", "lalu", "selain itu", "yang tadi",
    "what about", "tell me more", "and ", "its ", "their ", "that one",
)


def detect_followup(question: str, history: list[dict] | None) -> bool:
    """Decide whether ``question`` is a FOLLOW_UP (refers to the previous turn)
    or a NEW_TOPIC. Conservative by design: when uncertain, return NEW_TOPIC so
    a fresh question never inherits the previous turn's entity/topic context
    (the SIA-after-FASILKOM leakage). Deterministic, no LLM."""
    prior_user = [m for m in (history or []) if m.get("role") == "user" and (m.get("content") or "").strip()]
    if not prior_user:
        return False  # nothing to follow up on
    t = re.sub(r"\s+", " ", (question or "").strip().lower())
    if not t:
        return False

    cur_intent = detect_intent(question)
    prev_intent = detect_intent(prior_user[-1].get("content") or "")
    has_marker = _has(t, *_FOLLOWUP_MARKERS) or t.startswith(("dan ", "lalu ", "terus ", "kalau ", "and ", "what about"))
    token_count = len(t.split())

    # A clearly different, self-contained topical/system intent → NEW_TOPIC,
    # even if a stray pronoun appears (e.g. "Bagaimana cara akses SIA?").
    specific = {
        INTENT_TUITION, INTENT_SCHOLARSHIP, INTENT_CAMPUS, INTENT_SIA, INTENT_SSO,
        INTENT_LIBRARY, INTENT_ADMISSIONS, INTENT_ACADEMIC_CALENDAR,
        INTENT_ACADEMIC_REGULATIONS, INTENT_STUDENT_SERVICES,
    }
    if cur_intent in specific and cur_intent != prev_intent:
        return False
    if has_marker:
        return True
    # Short, subject-omitting question that stays within the prior topic.
    if token_count <= 4 and (cur_intent == INTENT_GENERAL or cur_intent == prev_intent):
        return True
    return False  # uncertain → NEW_TOPIC


# v3 P2 — per-intent host allowlists. A context on a compatible host is boosted;
# an official-but-off-intent VECTOR chunk is heavily penalised so, e.g., a SIA
# login query can never be answered by a tuition page. Hosts are subdomain labels.
INTENT_HOSTS: dict[str, set[str]] = {
    INTENT_SIA: {"sia", "sso", "support", "bti", "akademik", "baa"},
    INTENT_SSO: {"sso", "sia", "support", "bti"},
    INTENT_TUITION: {"pendaftaran", "pmb", "www"},
    INTENT_SCHOLARSHIP: {"ditmawa", "kemahasiswaan", "pendaftaran", "pmb"},
    INTENT_ADMISSIONS: {"pendaftaran", "pmb", "penerimaan"},
    INTENT_ACADEMIC_CALENDAR: {"baa", "akademik"},
    INTENT_ACADEMIC_REGULATIONS: {"baa", "akademik"},
    INTENT_LIBRARY: {"lib", "library", "perpustakaan", "digilib"},
    INTENT_STUDENT_SERVICES: {"support", "baa", "ditmawa", "kemahasiswaan", "bak", "ult"},
}

_HOST_BOOST = 3.0
_HOST_PENALTY = 6.0


def _host_label(hostname: str | None, root_domain: str = "mercubuana.ac.id") -> str:
    host = (hostname or "").lower().strip()
    if not host or not host.endswith(root_domain):
        return ""
    if host == root_domain:
        return "www"
    sub = host[: -(len(root_domain) + 1)]
    return sub.split(".")[-1] if sub else ""


def apply_intent_host_filter(query: str, contexts: list[dict], *, intent: str | None = None,
                             root_domain: str = "mercubuana.ac.id") -> list[dict]:
    """Hard intent→host ranking signal: boost compatible hosts, heavily penalise an
    official-but-off-intent vector chunk. Structured (FAQ/entity/graph) and already
    intent-demoted contexts are left to their own scores. Re-sorts by score."""
    from app.trust.authority import host_authority

    resolved = intent or detect_intent(query)
    allow = INTENT_HOSTS.get(resolved)
    if not allow:
        return contexts
    for ctx in contexts:
        host = (ctx.get("hostname") or "").lower()
        label = _host_label(host, root_domain)
        if label and label in allow:
            ctx["score"] = float(ctx.get("score") or 0.0) + _HOST_BOOST
            ctx["intent_host"] = "compatible"
        elif (
            ctx.get("source_type") not in {"faq", "entity", "graph"}
            and not ctx.get("intent_demoted")
            and host
            and host_authority(host, root_domain) >= 0.5
        ):
            # official vector chunk on the wrong host for this intent → penalise.
            ctx["score"] = float(ctx.get("score") or 0.0) - _HOST_PENALTY
            ctx["intent_host"] = "incompatible"
    contexts.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
    return contexts


def is_compatible(entity_type: str | None, intent: str) -> bool:
    compatible = INTENT_COMPATIBLE_ENTITY_TYPES.get(intent)
    if compatible is None:  # general / unknown intent → no constraint
        return True
    return entity_type in compatible


def apply_entity_intent_compatibility(query: str, contexts: list[dict], *, intent: str | None = None) -> list[dict]:
    """Demote structured contexts whose entity type is incompatible with the
    query intent. FAQ contexts are topical by construction and never demoted.
    Mutates+returns the same list (re-sorted by score)."""
    resolved_intent = intent or detect_intent(query)
    for ctx in contexts:
        source_type = ctx.get("source_type")
        if source_type == "faq":
            # A broad/off-topic FAQ (e.g. the faculty/program-list FAQ) must not
            # answer a specific topical question (admissions, tuition, …).
            if not _faq_compatible(ctx.get("faq_category"), resolved_intent):
                ctx["score"] = min(float(ctx.get("score") or 0.0), INCIDENTAL_SCORE)
                ctx["intent_demoted"] = True
                ctx["demoted_for_intent"] = resolved_intent
            continue
        if source_type not in {"entity", "graph"}:
            continue
        if not is_compatible(ctx.get("entity_type"), resolved_intent):
            ctx["score"] = min(float(ctx.get("score") or 0.0), INCIDENTAL_SCORE)
            ctx["intent_demoted"] = True
            ctx["demoted_for_intent"] = resolved_intent
    contexts.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)
    return contexts
