"""Phase 27.2 — session-history regression tests.

Invariant: one conversation = exactly one chat_sessions row. _ensure_session must
REUSE an existing session id (never duplicate), and a long conversation that keeps
sending the same (valid) session id must not create extra histories.
"""

from __future__ import annotations

from app.api.routes_chat import ChatRequest, _ensure_session
from app.chat.session_service import create_session, list_sessions


def test_existing_session_is_reused_not_duplicated(db):
    session = create_session(db, "anon-history")
    for i in range(50):  # 50-turn conversation
        payload = ChatRequest(session_id=session.id, anonymous_session_id="anon-history", question=f"q{i}")
        got = _ensure_session(db, payload)
        assert got.id == session.id
    assert len(list_sessions(db, "anon-history")) == 1  # exactly ONE history entry


def test_missing_session_id_creates_single_session(db):
    payload = ChatRequest(session_id=None, anonymous_session_id="anon-new", question="halo")
    s = _ensure_session(db, payload)
    # subsequent turns adopt the returned id -> still one session
    for i in range(10):
        p = ChatRequest(session_id=s.id, anonymous_session_id="anon-new", question=f"q{i}")
        assert _ensure_session(db, p).id == s.id
    assert len(list_sessions(db, "anon-new")) == 1


def test_stale_session_id_recovers_to_one_session(db):
    """A stale/unknown id creates one fresh session; the client then adopts the
    returned id (frontend fix), so further turns reuse it -> one history."""
    stale = "00000000-0000-0000-0000-0000deadbeef"
    first = _ensure_session(db, ChatRequest(session_id=stale, anonymous_session_id="anon-stale", question="x"))
    assert first.id != stale
    for i in range(10):  # client adopted first.id
        assert _ensure_session(db, ChatRequest(session_id=first.id, anonymous_session_id="anon-stale", question=f"q{i}")).id == first.id
    assert len(list_sessions(db, "anon-stale")) == 1
