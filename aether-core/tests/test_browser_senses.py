from __future__ import annotations

import sqlite3
from pathlib import Path

from aether.browser_senses import BrowserSenseStore
from aether.contracts import (
    BrowserSenseCapability,
    BrowserSenseSession,
    BrowserSenseSessionState,
    BrowserSenseTransport,
)


def _session() -> BrowserSenseSession:
    return BrowserSenseSession(
        session_id="sense-session.1",
        room_name="aether-room-1",
        participant_identity="founder-1",
        capabilities=(BrowserSenseCapability.TEXT, BrowserSenseCapability.MICROPHONE),
        transports=(BrowserSenseTransport.LIVEKIT, BrowserSenseTransport.HTTP_KEYFRAME),
        state=BrowserSenseSessionState.ISSUED,
        issued_at="2026-07-28T00:00:00Z",
        expires_at="2026-07-28T01:00:00Z",
        token_hash="a" * 64,
        principal="founder",
    )


def test_browser_sense_session_hash_and_append_only_store(tmp_path: Path) -> None:
    store = BrowserSenseStore(tmp_path / "senses.sqlite3")
    session = store.record_session(_session())
    active = store.transition_session(session.session_id, BrowserSenseSessionState.ACTIVE, recorded_at="2026-07-28T00:00:05Z")

    assert active.state is BrowserSenseSessionState.ACTIVE
    assert store.get_session(session.session_id).state is BrowserSenseSessionState.ACTIVE
    assert store.get_session_by_room(session.room_name).session_id == session.session_id
    assert store.status()["session_events"] == 2

    with sqlite3.connect(store.path) as conn:
        try:
            conn.execute("UPDATE browser_sense_sessions SET state='closed'")
        except sqlite3.DatabaseError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("browser sense evidence must be append-only")
