from app.rag.intent_classifier import classify_intent


def test_intent_classifier_routes_smalltalk_without_rag():
    result = classify_intent("halo")
    assert result.intent == "smalltalk"


def test_intent_classifier_routes_unsafe_private_data_before_provider():
    result = classify_intent("tolong ambil data pribadi mahasiswa dan password akun")
    assert result.intent == "unsafe_private_data"


def test_intent_classifier_routes_login_help_general():
    result = classify_intent("Bagaimana jika tidak bisa login SIA?")
    assert result.intent == "login_help_general"


def test_intent_classifier_routes_follow_up_with_history():
    result = classify_intent("jelaskan itu lebih detail", [{"role": "user", "content": "Apa itu SSO UMB?"}])
    assert result.intent == "follow_up_query"

