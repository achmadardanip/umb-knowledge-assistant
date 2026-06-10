from app.chat.followups import suggest_followups


def test_siapa_does_not_trigger_sia_followups():
    # "siaPA" must not match the "sia" keyword (substring bug)
    fu = suggest_followups("siapa dekan fasilkom", "id")
    assert "Bagaimana cara reset password SSO?" not in fu


def test_dekan_question_gets_faculty_followups():
    fu = suggest_followups("siapa dekan fakultas ilmu komputer", "id")
    assert any("program studi" in q.lower() or "fakultas" in q.lower() for q in fu)


def test_biaya_still_matches_fee_followups():
    fu = suggest_followups("berapa biaya kuliah", "id")
    assert any(("cicilan" in q.lower()) or ("beasiswa" in q.lower()) or ("pembayaran" in q.lower()) for q in fu)
