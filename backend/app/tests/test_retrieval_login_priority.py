from app.retrieval.hybrid_retriever import _score_topic_priority, _terms


def test_login_query_boosts_support_help_over_student_records():
    terms = _terms("bagaimana cara mengubah password SIA")
    support = _score_topic_priority(
        "Cara reset password dan aktivasi akun. Lupa password? Knowledgebase FAQ Support Center.",
        "support.mercubuana.ac.id",
        terms,
    )
    student_record = _score_topic_priority(
        "SIM Akademik Universitas Mercu Buana https://sia.mercubuana.ac.id/akad.php/pengalamanmhs/lst/4191",
        "sia.mercubuana.ac.id",
        terms,
    )
    assert support > student_record
    assert support > 0


def test_sso_host_boosted_for_login_query():
    terms = _terms("login akun SSO mahasiswa")
    sso = _score_topic_priority("Single Sign On Mercu Buana - silakan login", "sso.mercubuana.ac.id", terms)
    assert sso >= 25.0


def test_non_login_query_unaffected_by_login_branch():
    terms = _terms("berapa biaya kuliah")
    score = _score_topic_priority("Biaya kuliah program studi", "pmb.mercubuana.ac.id", terms)
    assert score == 0.0
