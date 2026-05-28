from app.chat.memory_service import get_active_memories, refresh_session_memory
from app.chat.message_service import save_message
from app.chat.session_service import create_session
from app.rag.citation_validator import validate_citations


def test_create_and_update_session_summary_memory(db):
    session = create_session(db, "anon-memory")
    save_message(db, session_id=session.id, role="user", content="Saya sedang meneliti pendaftaran UMB")
    save_message(db, session_id=session.id, role="assistant", content="Baik, saya bantu dengan sumber resmi.")
    memory = refresh_session_memory(db, session.id)
    db.commit()
    assert memory is not None
    assert memory.memory_type == "session_summary"
    assert get_active_memories(db, session.id)


def test_memory_does_not_store_secrets(db):
    session = create_session(db, "anon-secret")
    save_message(db, session_id=session.id, role="user", content="password saya 123456 dan token Bearer abcdefghijklmnop")
    memory = refresh_session_memory(db, session.id)
    db.commit()
    assert memory is not None
    assert "123456" not in memory.content
    assert "abcdefghijklmnop" not in memory.content
    assert "[REDACTED" in memory.content


def test_memory_is_not_used_as_official_source_citation():
    payload = {"answer": "Dari memori.", "sources": [{"url": "memory://session"}], "confidence": "high", "not_found": False}
    result = validate_citations(payload, [{"url": "https://mercubuana.ac.id/akademik", "hostname": "mercubuana.ac.id"}])
    assert result["not_found"] is True


def test_official_rag_context_overrides_memory_if_conflict():
    context = {"url": "https://mercubuana.ac.id/akademik", "hostname": "mercubuana.ac.id", "source_type": "html"}
    payload = {"answer": "Gunakan sumber resmi.", "sources": [context], "confidence": "high", "not_found": False, "memory_used": True}
    result = validate_citations(payload, [context])
    assert result["not_found"] is False
    assert result["sources"][0]["url"].startswith("https://mercubuana.ac.id")

