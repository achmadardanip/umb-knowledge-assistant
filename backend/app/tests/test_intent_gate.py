"""Tests for the intent gate, built from the observed bad behaviors:

1. "Bagaimana jika tidak bisa login SIA?" retrieved repository thesis pages.
2. "Ke mana menghubungi dukungan teknis?" answered from a finance page.
3. "siapa dekan fasilkom" cited Biaya Kuliah + repository subject pages.
4. "Bagaimana cara reset password SIA/SSO?" cited Biaya Kuliah.
"""

from app.retrieval.intent_gate import (
    detect_retrieval_intent,
    gate_contexts,
    history_conflicts,
    live_query_for_intent,
    refusal_message,
    should_trigger_live_fallback,
)


def _ctx(url: str, title: str, text: str, hostname: str | None = None) -> dict:
    host = hostname or url.split("/")[2]
    return {"url": url, "title": title, "chunk_text": text, "hostname": host, "score": 10.0}


REPO_THESIS = _ctx(
    "https://repository.mercubuana.ac.id/12345/",
    "IMPLEMENTASI CHATBOT CUACA BERBASIS SBERT",
    "Skripsi penelitian chatbot cuaca berbasis SBERT pada Fakultas Teknik. Browse by Year repository.",
)
REPO_SUBJECT = _ctx(
    "https://repository.mercubuana.ac.id/view/subjects/S006.html",
    "Browse by Subject",
    "Browse by Year where Division is Fakultas Teknik repository subject listing skripsi tesis.",
)
BIAYA_KULIAH = _ctx(
    "https://pendaftaran.mercubuana.ac.id/rincian-pembayaran",
    "Biaya Kuliah - Universitas Mercu Buana",
    "Rincian pembayaran biaya kuliah pendaftaran mahasiswa baru PMB gelombang.",
)
SUPPORT_CENTER = _ctx(
    "https://support.mercubuana.ac.id/kb/faq.php?id=3",
    "Support Center UMB",
    "Bantuan reset password akun SIA dan SSO. Hubungi helpdesk support center, buka tiket bantuan.",
)
SIA_PORTAL = _ctx(
    "https://sia.mercubuana.ac.id/",
    "SIM Akademik UMB",
    "Sistem Informasi Akademik Universitas Mercu Buana. Login SIA dengan akun SSO. Lupa password hubungi support.",
)
FASILKOM_STRUKTUR = _ctx(
    "https://mercubuana.ac.id/struktural-dan-dosen-fasilkom",
    "Struktural dan Dosen Fasilkom",
    "Struktur organisasi Fakultas Ilmu Komputer. Dekan Fakultas Ilmu Komputer dan program studi Teknik Informatika.",
)


# ---------- intent detection ----------

def test_detects_login_intent_for_sia_password_questions():
    assert detect_retrieval_intent("Bagaimana cara reset password SIA?") == "login_help"
    assert detect_retrieval_intent("Bagaimana jika tidak bisa login SIA?") == "login_help"
    assert detect_retrieval_intent("Bagaimana cara reset password SSO?") == "login_help"


def test_detects_support_intent():
    assert detect_retrieval_intent("Ke mana menghubungi dukungan teknis?") == "support"


def test_detects_faculty_intent_for_dean():
    assert detect_retrieval_intent("siapa dekan fasilkom") == "faculty"


def test_repository_intent_only_when_explicit():
    assert detect_retrieval_intent("cara akses repository skripsi UMB") == "repository"
    assert detect_retrieval_intent("Bagaimana jika tidak bisa login SIA?") != "repository"


# ---------- hard filtering (the 4 observed failures) ----------

def test_login_query_rejects_repository_and_fee_pages():
    kept, rejected = gate_contexts(
        "Bagaimana cara reset password SIA?", "login_help",
        [REPO_THESIS, BIAYA_KULIAH, SUPPORT_CENTER, SIA_PORTAL],
    )
    kept_urls = {c["url"] for c in kept}
    assert SUPPORT_CENTER["url"] in kept_urls
    assert SIA_PORTAL["url"] in kept_urls
    assert all("repository." not in c["url"] for c in kept)
    assert all("pendaftaran." not in c["url"] for c in kept)
    assert len(rejected) == 2
    assert all(c.get("_reject_reason") for c in rejected)


def test_support_query_rejects_finance_and_repo():
    kept, rejected = gate_contexts(
        "Ke mana menghubungi dukungan teknis?", "support",
        [BIAYA_KULIAH, REPO_SUBJECT, SUPPORT_CENTER],
    )
    assert [c["url"] for c in kept] == [SUPPORT_CENTER["url"]]
    assert len(rejected) == 2


def test_dean_query_rejects_fee_and_repo_keeps_struktur():
    kept, rejected = gate_contexts(
        "siapa dekan fasilkom", "faculty",
        [BIAYA_KULIAH, REPO_SUBJECT, FASILKOM_STRUKTUR],
    )
    assert [c["url"] for c in kept] == [FASILKOM_STRUKTUR["url"]]
    assert {c["url"] for c in rejected} == {BIAYA_KULIAH["url"], REPO_SUBJECT["url"]}


def test_general_intent_does_not_hard_filter():
    kept, _rejected = gate_contexts(
        "informasi umum kampus", "general",
        [BIAYA_KULIAH, SUPPORT_CENTER],
    )
    assert len(kept) == 2


def test_repository_intent_allows_repository_pages():
    kept, _ = gate_contexts(
        "cara akses repository skripsi", "repository",
        [REPO_SUBJECT, SUPPORT_CENTER],
    )
    assert REPO_SUBJECT["url"] in {c["url"] for c in kept}


# ---------- fallback decision ----------

def test_fallback_triggers_when_all_contexts_rejected():
    kept, _ = gate_contexts(
        "Bagaimana cara reset password SSO?", "login_help",
        [BIAYA_KULIAH, REPO_THESIS],
    )
    trigger, reason = should_trigger_live_fallback("login_help", kept)
    assert kept == []
    assert trigger is True
    assert reason


def test_fallback_not_triggered_with_answerable_context():
    kept, _ = gate_contexts(
        "Bagaimana cara reset password SIA?", "login_help",
        [SUPPORT_CENTER],
    )
    trigger, _ = should_trigger_live_fallback("login_help", kept)
    assert trigger is False


def test_sensitive_login_portal_without_help_pattern_triggers_fallback():
    """A SIA login *portal* (right terms, no reset guide) is not a real answer -> try live."""
    portal = _ctx(
        "https://sia.mercubuana.ac.id/",
        "SIM Akademik Universitas Mercu Buana",
        "Sistem Informasi Akademik UMB. Login SIA menggunakan akun dan password SSO Anda.",
    )
    kept, _ = gate_contexts("Bagaimana cara reset password SIA?", "login_help", [portal])
    assert kept, "portal should pass the domain/term gate"
    trigger, reason = should_trigger_live_fallback("login_help", kept)
    assert trigger is True
    assert "pattern" in (reason or "")


def test_sensitive_help_page_with_pattern_does_not_trigger():
    help_pg = _ctx(
        "https://support.mercubuana.ac.id/kb/faq",
        "Support Center UMB",
        "Lupa password SIA? Klik menu reset password, lalu hubungi helpdesk untuk bantuan tiket.",
    )
    kept, _ = gate_contexts("Bagaimana cara reset password SIA?", "login_help", [help_pg])
    trigger, _ = should_trigger_live_fallback("login_help", kept)
    assert trigger is False


def test_live_query_is_intent_enriched():
    q = live_query_for_intent("Bagaimana cara reset password SIA?", "login_help")
    assert "password" in q.lower() and ("sia" in q.lower() or "sso" in q.lower())


# ---------- refusal templates ----------

def test_login_refusal_is_safe_and_specific():
    msg = refusal_message("login_help", "id")
    assert "tidak akan menebak" in msg.lower()
    assert "support" in msg.lower() or "ult" in msg.lower() or "baa" in msg.lower()


def test_faculty_refusal_mentions_struktur():
    msg = refusal_message("faculty", "id")
    assert "fasilkom" in msg.lower() or "fakultas" in msg.lower()


def test_general_intent_has_no_special_refusal():
    assert refusal_message("general", "id") is None


# ---------- conversation context conflict ----------

def test_fasilkom_history_conflicts_with_login_query():
    assert history_conflicts("login_help", "Informasi Fasilkom UMB") is True


def test_matching_history_does_not_conflict():
    assert history_conflicts("faculty", "Informasi Fasilkom UMB") is False


def test_general_history_never_conflicts():
    assert history_conflicts("login_help", "Halo, terima kasih infonya") is False
