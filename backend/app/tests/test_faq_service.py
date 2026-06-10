from app.chat.faq_service import top_faq, top_questions
from app.db.models import ChatMessage, ChatSession


def _session(db):
    session = ChatSession(anonymous_session_id="anon-faq")
    db.add(session)
    db.flush()
    return session


def _ask(db, session_id, text):
    db.add(ChatMessage(session_id=session_id, role="user", content=text))
    db.commit()


def test_top_questions_ranks_by_frequency(db):
    session = _session(db)
    for _ in range(3):
        _ask(db, session.id, "Bagaimana cara daftar mahasiswa baru di UMB?")
    _ask(db, session.id, "Apa itu SSO Universitas Mercu Buana?")

    result = top_questions(db, limit=6)

    assert result[0]["question"] == "Bagaimana cara daftar mahasiswa baru di UMB?"
    assert result[0]["count"] == 3


def test_top_questions_ignores_short_noise(db):
    session = _session(db)
    for _ in range(5):
        _ask(db, session.id, "hai")  # too short to be an FAQ
    result = top_questions(db, limit=6)
    assert result == []


def test_top_faq_fills_with_curated_defaults_when_sparse(db):
    # No user messages -> 6 curated defaults so the home page is never empty.
    result = top_faq(db, limit=6)
    assert len(result) == 6
    assert all(isinstance(q, str) and len(q) > 10 for q in result)
