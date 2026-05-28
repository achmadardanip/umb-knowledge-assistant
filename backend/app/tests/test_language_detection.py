from app.rag.language import detect_language


def test_detect_language_indonesian():
    assert detect_language("Bagaimana cara daftar mahasiswa baru?") == "id"


def test_detect_language_english():
    assert detect_language("How can I apply for admission?") == "en"

