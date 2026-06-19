from datetime import timedelta

from app.api.routes_chat import ChatRequest, process_chat
from app.chat.message_service import recent_messages, save_message
from app.chat.session_service import archive_session, create_session, list_sessions, load_messages, maybe_autotitle_session, rename_session
from app.chat.title_generator import generate_title_from_question
from app.db.models import Chunk, Document, Source, utcnow


def test_create_new_chat_session(db):
    session = create_session(db, "anon-1")
    assert session.title == "New Chat"
    assert session.anonymous_session_id == "anon-1"


def test_auto_generate_title_from_first_message(db):
    session = create_session(db, "anon-title")
    save_message(db, session_id=session.id, role="user", content="Bagaimana cara daftar mahasiswa baru?")
    title = maybe_autotitle_session(db, session.id, "Bagaimana cara daftar mahasiswa baru?")
    db.commit()
    assert title == "Daftar Mahasiswa Baru"
    # Acronyms are preserved (Phase 13): "SSO" stays uppercase, not "Sso".
    assert generate_title_from_question("Apa itu SSO Universitas Mercu Buana?") == "SSO Universitas Mercu Buana"


def test_save_user_and_assistant_messages_under_correct_session(db):
    session = create_session(db, "anon-msg")
    user = save_message(db, session_id=session.id, role="user", content="Halo")
    assistant = save_message(db, session_id=session.id, role="assistant", content="Halo juga", sources=[], confidence_score="low")
    db.commit()
    messages = load_messages(db, session.id)
    assert [message.id for message in messages] == [user.id, assistant.id]
    assert recent_messages(db, session.id)[-1]["content"] == "Halo juga"


def test_retrieve_chat_history_sorted_by_last_message_at(db):
    old = create_session(db, "anon-sort")
    new = create_session(db, "anon-sort")
    old.last_message_at = utcnow() - timedelta(days=1)
    new.last_message_at = utcnow()
    db.commit()
    sessions = list_sessions(db, "anon-sort")
    assert sessions[0].id == new.id


def test_load_messages_rename_and_soft_delete_session(db):
    session = create_session(db, "anon-edit")
    save_message(db, session_id=session.id, role="user", content="Tes")
    db.commit()
    assert len(load_messages(db, session.id)) == 1
    renamed = rename_session(db, session.id, "Judul Baru")
    assert renamed.title == "Judul Baru"
    assert archive_session(db, session.id)
    assert list_sessions(db, "anon-edit") == []


def test_hidden_chain_of_thought_is_never_stored_or_returned(db):
    session = create_session(db, "anon-think")
    message = save_message(db, session_id=session.id, role="user", content="<think>secret</think>Halo")
    db.commit()
    assert "secret" not in message.content
    assert "<think>" not in message.content


def test_anonymous_session_id_can_own_multiple_sessions(db):
    create_session(db, "anon-many")
    create_session(db, "anon-many")
    assert len(list_sessions(db, "anon-many")) == 2


def test_process_chat_emits_dynamic_operational_steps(db, monkeypatch):
    source = Source(
        url="https://pmb.mercubuana.ac.id/pendaftaran",
        title="Pendaftaran Mahasiswa Baru",
        hostname="pmb.mercubuana.ac.id",
        path="/pendaftaran",
        status="indexed",
        discovery_source="katana",
    )
    db.add(source)
    db.flush()
    document = Document(source_id=source.id, raw_text="pendaftaran mahasiswa baru", cleaned_text="pendaftaran mahasiswa baru")
    db.add(document)
    db.flush()
    db.add(
        Chunk(
            document_id=document.id,
            source_id=source.id,
            chunk_text="Informasi pendaftaran mahasiswa baru Universitas Mercu Buana melalui PMB.",
            chunk_index=0,
            token_count=10,
            source_type="html",
            meta={
                "url": source.url,
                "hostname": source.hostname,
                "path": source.path,
                "title": source.title,
                "source_type": "html",
                "discovery_source": "katana",
            },
        )
    )
    db.commit()

    def fake_provider_meta(provider_override):
        return provider_override or "openrouter", "test-model"

    def fake_generate_answer(**kwargs):
        context = kwargs["contexts"][0]
        return {
            "answer": "Pendaftaran tersedia melalui PMB.",
            "sources": [
                {
                    "title": context["title"],
                    "url": context["url"],
                    "hostname": context["hostname"],
                    "source_type": context["source_type"],
                    "relevance_score": context["score"],
                    "discovery_source": context["discovery_source"],
                }
            ],
            "confidence": "high",
            "not_found": False,
            "provider_used": "openrouter",
            "model_used": "test-model",
            "memory_used": False,
        }

    monkeypatch.setattr("app.api.routes_chat._provider_meta", fake_provider_meta)
    monkeypatch.setattr("app.api.routes_chat.generate_answer", fake_generate_answer)

    emitted_steps = []
    result = process_chat(
        ChatRequest(
            anonymous_session_id="anon-agent",
            question="Bagaimana cara daftar mahasiswa baru?",
            provider_override="openrouter",
            memory_enabled=False,
        ),
        db,
        emit_step=emitted_steps.append,
    )

    assert result["sources"][0]["hostname"] == "pmb.mercubuana.ac.id"
    assert {step["id"] for step in emitted_steps} >= {"guardrail", "retrieval", "provider", "save_answer"}
    assert all({"id", "label", "status", "metadata"}.issubset(step) for step in emitted_steps)
    saved_assistant = load_messages(db, result["session_id"])[-1]
    assert saved_assistant.visible_steps
    assert all("<think>" not in str(step).lower() for step in saved_assistant.visible_steps)
