from app.chat.followups import suggest_followups


def test_admission_question_gets_admission_followups():
    out = suggest_followups("Bagaimana cara daftar mahasiswa baru?", language="id")
    assert 1 <= len(out) <= 3
    joined = " ".join(out).lower()
    assert any(word in joined for word in ["biaya", "syarat", "jadwal", "gelombang"])


def test_english_question_gets_english_followups():
    out = suggest_followups("What is the tuition fee at UMB?", language="en")
    assert 1 <= len(out) <= 3
    joined = " ".join(out).lower()
    assert any(word in joined for word in ["how", "what", "when", "where", "is", "are", "can"])


def test_unknown_question_falls_back_to_defaults():
    out = suggest_followups("xyzzy", language="id")
    assert 1 <= len(out) <= 3
