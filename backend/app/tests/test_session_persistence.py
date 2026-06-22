"""Phase 27.2 — session persistence tests.

Backend invariants behind the UX requirements:
  * page reload / browser refresh preserves the same session (no new history)
  * a new session is created only on New Chat (no session_id) or after delete/expire
"""

from __future__ import annotations

from app.api.routes_chat import ChatRequest, _ensure_session
from app.chat.session_service import archive_session, create_session, get_session, list_sessions, load_messages
from app.db.models import ChatMessage


def _add_turn(db, session_id, i):
    db.add(ChatMessage(session_id=session_id, role="user", content=f"q{i}"))
    db.add(ChatMessage(session_id=session_id, role="assistant", content=f"a{i}"))
    db.commit()


def test_reload_preserves_same_session(db):
    s = create_session(db, "anon-reload")
    for i in range(5):
        _add_turn(db, s.id, i)
    # "reload": fetch the session + its messages again -> same id, messages intact, 1 history
    again = get_session(db, s.id)
    assert again is not None and again.id == s.id
    assert len(load_messages(db, s.id)) == 10
    assert len(list_sessions(db, "anon-reload")) == 1


def test_refresh_does_not_create_new_session(db):
    s = create_session(db, "anon-refresh")
    # repeated _ensure_session with the SAME id (what a refresh + continued chat does)
    for i in range(20):
        assert _ensure_session(db, ChatRequest(session_id=s.id, anonymous_session_id="anon-refresh", question=f"q{i}")).id == s.id
    assert len(list_sessions(db, "anon-refresh")) == 1


def test_new_session_only_on_explicit_new_chat(db):
    # "New Chat" = no session_id -> exactly one new session per click
    a = _ensure_session(db, ChatRequest(session_id=None, anonymous_session_id="anon-explicit", question="hi"))
    b = _ensure_session(db, ChatRequest(session_id=None, anonymous_session_id="anon-explicit", question="hi again"))
    assert a.id != b.id
    assert len(list_sessions(db, "anon-explicit")) == 2  # two explicit New Chats


def test_deleted_session_is_removed(db):
    s = create_session(db, "anon-del")
    assert archive_session(db, s.id) is True
    assert get_session(db, s.id) is None  # excluded after delete
    assert all(x.session_id != s.id for x in list_sessions(db, "anon-del"))
