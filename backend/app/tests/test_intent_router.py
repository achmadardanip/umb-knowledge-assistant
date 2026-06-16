"""Tests for v2 intent routing + entity-intent compatibility (entity over-firing fix)."""

from __future__ import annotations

import pytest

from app.rag.intent_router import (
    INCIDENTAL_SCORE,
    FOLLOWUP_CONFIDENCE_THRESHOLD,
    analyze_followup,
    apply_entity_intent_compatibility,
    apply_intent_host_filter,
    detect_followup,
    detect_intent,
    is_compatible,
    _host_label,
)


# --- v3 P2: intent-aware host hard filter -------------------------------------
def test_host_label():
    assert _host_label("sia.mercubuana.ac.id") == "sia"
    assert _host_label("mercubuana.ac.id") == "www"
    assert _host_label("evil.com") == ""


def _vec(host, score, st="html"):
    return {"hostname": host, "score": score, "source_type": st}


def test_sia_login_penalises_tuition_page():
    # "cara login sia" must rank a SIA host above a tuition (pendaftaran) page
    contexts = [
        _vec("pendaftaran.mercubuana.ac.id", 5.0),   # tuition page, high cosine
        _vec("sia.mercubuana.ac.id", 2.0),           # SIA page, lower cosine
    ]
    apply_intent_host_filter("cara login sia", contexts)
    assert contexts[0]["hostname"] == "sia.mercubuana.ac.id"
    assert contexts[0]["intent_host"] == "compatible"
    assert any(c.get("intent_host") == "incompatible" for c in contexts)


def test_tuition_penalises_sia_page():
    contexts = [_vec("sia.mercubuana.ac.id", 5.0), _vec("pendaftaran.mercubuana.ac.id", 2.0)]
    apply_intent_host_filter("berapa biaya kuliah", contexts)
    assert contexts[0]["hostname"] == "pendaftaran.mercubuana.ac.id"


def test_host_filter_does_not_penalise_structured():
    contexts = [_vec("pendaftaran.mercubuana.ac.id", 12.0, st="faq")]
    apply_intent_host_filter("cara login sia", contexts)
    # a structured (faq) context is never penalised by the host filter
    assert contexts[0]["score"] == 12.0


def test_host_filter_noop_for_unlisted_intent():
    contexts = [_vec("ft.mercubuana.ac.id", 3.0), _vec("fasilkom.mercubuana.ac.id", 2.0)]
    before = [c["score"] for c in contexts]
    apply_intent_host_filter("siapa dekan fasilkom", contexts)  # lecturer intent, no host allowlist
    assert [c["score"] for c in contexts] == before


def _hist(*user_msgs):
    return [{"role": "user", "content": m} for m in user_msgs]


# --- follow-up vs new-topic detection (Batch 2) ------------------------------
def test_followup_false_without_history():
    assert detect_followup("Bagaimana cara akses SIA?", []) is False
    assert detect_followup("Apa itu?", None) is False


def test_sia_after_fasilkom_is_new_topic():
    # the leakage case: a fresh SIA question must NOT inherit FASILKOM context
    hist = _hist("Siapa dekan Fakultas Ilmu Komputer?")
    assert detect_followup("Bagaimana cara saya login ke SIA?", hist) is False


def test_pronoun_continuation_is_followup():
    hist = _hist("Siapa dekan Fakultas Ilmu Komputer?")
    assert detect_followup("Bagaimana dengan program studinya?", hist) is True


def test_more_detail_is_followup():
    hist = _hist("Apa saja program studi di Fakultas Teknik?")
    assert detect_followup("jelaskan lebih detail", hist) is True


def test_different_specific_intent_is_new_topic():
    hist = _hist("Berapa biaya kuliah Informatika?")  # tuition
    assert detect_followup("Beasiswa apa saja yang tersedia?", hist) is False  # scholarship


def test_short_generic_continuation_is_followup():
    hist = _hist("Apa saja fasilitas kampus Meruya?")
    assert detect_followup("yang lainnya?", hist) is True


# --- P3 conversation-state isolation -----------------------------------------
def test_analyze_followup_structured_fields():
    hist = _hist("Siapa dekan Fakultas Ilmu Komputer?")
    d = analyze_followup("Bagaimana cara login SIA?", hist)
    assert d.is_followup is False
    assert d.confidence < FOLLOWUP_CONFIDENCE_THRESHOLD
    assert d.intent_changed is True  # lecturer -> sia
    assert d.cur_intent == "sia" and d.prev_intent == "lecturer"
    # is_followup must always agree with the confidence threshold
    assert d.is_followup == (d.confidence >= FOLLOWUP_CONFIDENCE_THRESHOLD)


def test_uts_question_is_academic_calendar_new_topic():
    # regression: "semester ini" determiner must not make a calendar question a
    # follow-up of an unrelated faculty turn (the 12.5%-leakage bug the benchmark caught).
    assert detect_intent("Kapan jadwal UTS semester ini?") == "academic_calendar"
    hist = _hist("Siapa dekan Fakultas Ilmu Komputer?")
    d = analyze_followup("Kapan jadwal UTS semester ini?", hist)
    assert d.is_followup is False
    assert d.reason == "different_specific_intent"


def test_determiner_ini_itu_not_anaphora_in_new_specific_topic():
    hist = _hist("Apa saja program studi di Fakultas Teknik?")
    # a self-contained new specific intent ending in a determiner stays NEW_TOPIC
    assert analyze_followup("Berapa biaya semester ini?", hist).is_followup is False


def test_followup_context_isolation_benchmark_meets_targets():
    """The 348-conversation isolation benchmark must hit leakage<1% + followup_acc>95%."""
    from app.evaluation.followup_eval import evaluate

    report = evaluate()
    assert report["n_conversations"] >= 300
    assert report["context_leakage_rate"] < 0.01
    assert report["followup_accuracy"] > 0.95


# --- intent detection --------------------------------------------------------
@pytest.mark.parametrize(
    "query,expected",
    [
        ("Berapa biaya kuliah program Akuntansi?", "tuition"),
        ("Berapa uang pangkal Teknik Informatika?", "tuition"),
        ("Beasiswa apa saja yang tersedia?", "scholarship"),
        ("Bagaimana daftar KIP Kuliah?", "scholarship"),
        ("Di mana lokasi kampus Meruya?", "campus"),
        ("Alamat UMB di mana?", "campus"),
        ("Kapan kalender akademik dimulai?", "academic_calendar"),
        ("Bagaimana cara akses SIA?", "sia"),
        ("Apa portal SSO resmi?", "sso"),
        ("Bagaimana cara reset password login?", "sso"),
        ("Siapa dekan Fakultas Ilmu Komputer?", "lecturer"),
        ("Bagaimana cara daftar mahasiswa baru?", "admissions"),
        ("Di mana perpustakaan UMB?", "library"),
    ],
)
def test_detect_intent(query, expected):
    assert detect_intent(query) == expected


def test_detect_intent_empty_is_general():
    assert detect_intent("") == "general"
    assert detect_intent("apa kabar UMB") == "general"


# --- compatibility map -------------------------------------------------------
def test_tuition_demotes_all_entities():
    # tuition has no entity row → faculty/program/scholarship all incompatible
    assert not is_compatible("study_program", "tuition")
    assert not is_compatible("faculty", "tuition")
    assert not is_compatible("scholarship", "tuition")


def test_scholarship_keeps_scholarship_entity():
    assert is_compatible("scholarship", "scholarship")
    assert not is_compatible("study_program", "scholarship")
    assert not is_compatible("faculty", "scholarship")


def test_campus_keeps_campus_entity():
    assert is_compatible("campus", "campus")
    assert not is_compatible("faculty", "campus")


def test_lecturer_keeps_faculty_entity():
    assert is_compatible("faculty", "lecturer")
    assert not is_compatible("scholarship", "lecturer")


def test_general_allows_everything():
    for et in ("faculty", "study_program", "campus", "scholarship", "contact", "service"):
        assert is_compatible(et, "general")


# --- demotion application ----------------------------------------------------
def _ctx(entity_type, score, source_type="entity"):
    return {"entity_type": entity_type, "score": score, "source_type": source_type, "title": entity_type}


def test_demotes_incidental_program_under_tuition_intent():
    contexts = [_ctx("study_program", 10.0), _ctx("faculty", 10.0)]
    apply_entity_intent_compatibility("Berapa biaya kuliah program Akuntansi?", contexts)
    assert all(c["score"] == INCIDENTAL_SCORE and c["intent_demoted"] for c in contexts)


def test_keeps_compatible_scholarship_under_scholarship_intent():
    contexts = [_ctx("scholarship", 10.0), _ctx("study_program", 10.0)]
    apply_entity_intent_compatibility("beasiswa untuk program Arsitektur", contexts)
    sch = next(c for c in contexts if c["entity_type"] == "scholarship")
    prog = next(c for c in contexts if c["entity_type"] == "study_program")
    assert sch["score"] == 10.0 and not sch.get("intent_demoted")
    assert prog["score"] == INCIDENTAL_SCORE and prog["intent_demoted"]
    # compatible context re-sorted to the top
    assert contexts[0]["entity_type"] == "scholarship"


def test_never_demotes_faq():
    contexts = [_ctx("faq", 14.0, source_type="faq")]
    apply_entity_intent_compatibility("Berapa biaya kuliah?", contexts)
    assert contexts[0]["score"] == 14.0 and not contexts[0].get("intent_demoted")


def test_keeps_faculty_under_lecturer_intent():
    contexts = [_ctx("faculty", 10.0)]
    apply_entity_intent_compatibility("Siapa dekan Fakultas Ilmu Komputer?", contexts)
    assert contexts[0]["score"] == 10.0 and not contexts[0].get("intent_demoted")


def test_graph_relation_demoted_under_tuition():
    contexts = [_ctx("graph_relation", 9.0, source_type="graph")]
    apply_entity_intent_compatibility("Berapa biaya kuliah Akuntansi?", contexts)
    assert contexts[0]["intent_demoted"] and contexts[0]["score"] == INCIDENTAL_SCORE


def test_graph_relation_kept_under_study_program():
    contexts = [_ctx("graph_relation", 9.0, source_type="graph")]
    apply_entity_intent_compatibility("program studi di Fakultas Teknik", contexts)
    assert not contexts[0].get("intent_demoted")


def test_mendaftar_routes_to_admissions_not_study_program():
    # word-boundary regression: "mendaftar" must not fall through to study_program
    assert detect_intent("Bagaimana cara mendaftar program studi Akuntansi di UMB?") == "admissions"


def test_faculties_faq_demoted_under_admissions_intent():
    # the broad faculty/program-list FAQ must not answer an admissions question
    faq = {"source_type": "faq", "faq_category": "faculties", "score": 12.0, "entity_type": "faq"}
    apply_entity_intent_compatibility("cara mendaftar program studi Akuntansi", [faq])
    assert faq["intent_demoted"] and faq["score"] == INCIDENTAL_SCORE


def test_tuition_faq_kept_under_tuition_intent():
    faq = {"source_type": "faq", "faq_category": "tuition", "score": 12.0, "entity_type": "faq"}
    apply_entity_intent_compatibility("berapa biaya kuliah akuntansi", [faq])
    assert not faq.get("intent_demoted")


def test_faculties_faq_kept_under_study_program_intent():
    faq = {"source_type": "faq", "faq_category": "faculties", "score": 12.0, "entity_type": "faq"}
    apply_entity_intent_compatibility("program studi di fakultas teknik", [faq])
    assert not faq.get("intent_demoted")
