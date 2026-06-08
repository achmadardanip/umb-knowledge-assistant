from app.chat.clarify import clarifying_questions


def test_biaya_without_specifics_asks_for_program():
    qs = clarifying_questions("Berapa biaya kuliah di UMB?")
    assert qs  # non-empty: the topic is ambiguous (which program/level/class?)
    assert any("program" in q.lower() for q in qs)


def test_biaya_with_program_and_level_is_clear():
    assert clarifying_questions("Berapa biaya kuliah S1 Teknik Informatika kelas karyawan?") == []


def test_jadwal_alone_is_ambiguous():
    qs = clarifying_questions("jadwal")
    assert qs
    assert any("ujian" in q.lower() or "kuliah" in q.lower() for q in qs)


def test_specific_howto_is_clear():
    assert clarifying_questions("Bagaimana cara reset password SIA?") == []


def test_too_short_generic_asks_for_detail():
    assert clarifying_questions("info dong")


def test_english_topic_returns_english_questions():
    qs = clarifying_questions("How much is the tuition fee?", language="en")
    assert qs
    assert any("program" in q.lower() for q in qs)
    # must not leak Indonesian into an English clarification
    assert all("apa" not in q.lower() for q in qs)


def test_prior_turn_specifics_suppress_clarification():
    recent = [{"role": "user", "content": "Saya mau tanya soal S1 Teknik Informatika kelas karyawan"}]
    assert clarifying_questions("biaya kuliahnya berapa?", recent_messages=recent) == []


def test_suggestions_are_concrete_answerable_queries():
    from app.chat.clarify import clarification_suggestions

    sugg = clarification_suggestions("Berapa biaya kuliah di UMB?")
    assert sugg  # the chips a user can click
    # every suggestion must itself be specific (clicking it must NOT re-trigger clarification)
    assert all(clarifying_questions(s) == [] for s in sugg)


def test_clear_question_has_no_suggestions():
    from app.chat.clarify import clarification_suggestions

    assert clarification_suggestions("Bagaimana cara reset password SIA?") == []


def test_generic_query_offers_starter_suggestions():
    from app.chat.clarify import clarification_suggestions

    sugg = clarification_suggestions("info dong")
    assert sugg
    assert all(clarifying_questions(s) == [] for s in sugg)
