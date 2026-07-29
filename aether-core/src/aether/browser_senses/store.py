"""Append-only browser sense session, media, vision, and turn evidence."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from aether.contracts.browser_senses import (
    BrowserMediaTrackReceipt,
    BrowserSenseCapability,
    BrowserSenseSession,
    BrowserSenseSessionState,
    BrowserSenseTransport,
    BrowserSenseTurnReceipt,
    MediaTrackKind,
    VisionFrameReceipt,
)


class BrowserSenseStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS browser_sense_sessions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_sense_sessions_id
                    ON browser_sense_sessions(session_id, row_id DESC);
                CREATE TABLE IF NOT EXISTS browser_media_tracks (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_vision_frames (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_sense_turns (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS browser_sense_sessions_no_update
                BEFORE UPDATE ON browser_sense_sessions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_sessions_no_delete
                BEFORE DELETE ON browser_sense_sessions BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_media_tracks_no_update
                BEFORE UPDATE ON browser_media_tracks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_media_tracks_no_delete
                BEFORE DELETE ON browser_media_tracks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_vision_frames_no_update
                BEFORE UPDATE ON browser_vision_frames BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_vision_frames_no_delete
                BEFORE DELETE ON browser_vision_frames BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_turns_no_update
                BEFORE UPDATE ON browser_sense_turns BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_turns_no_delete
                BEFORE DELETE ON browser_sense_turns BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                """
            )

    @staticmethod
    def _json(value: Any) -> str:
        def default(item: Any) -> Any:
            return getattr(item, "value", str(item))
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=default)

    def record_session(self, session: BrowserSenseSession) -> BrowserSenseSession:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_sense_sessions(session_id,payload_json,state,fingerprint,recorded_at) VALUES(?,?,?,?,?)",
                (session.session_id, self._json(asdict(session)), session.state.value, session.fingerprint, session.issued_at),
            )
        return session

    def transition_session(self, session_id: str, state: BrowserSenseSessionState, *, recorded_at: str, metadata: dict[str, Any] | None = None) -> BrowserSenseSession:
        current = self.get_session(session_id)
        merged = {**dict(current.metadata), **dict(metadata or {}), "transitioned_at": recorded_at}
        updated = replace(current, state=state, metadata=merged, fingerprint="")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_sense_sessions(session_id,payload_json,state,fingerprint,recorded_at) VALUES(?,?,?,?,?)",
                (updated.session_id, self._json(asdict(updated)), updated.state.value, updated.fingerprint, recorded_at),
            )
        return updated

    def get_session(self, session_id: str) -> BrowserSenseSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM browser_sense_sessions WHERE session_id=? ORDER BY row_id DESC LIMIT 1",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(session_id)
        data = json.loads(row["payload_json"])
        return BrowserSenseSession(
            session_id=data["session_id"], room_name=data["room_name"], participant_identity=data["participant_identity"],
            capabilities=tuple(BrowserSenseCapability(item) for item in data["capabilities"]),
            transports=tuple(BrowserSenseTransport(item) for item in data["transports"]),
            state=BrowserSenseSessionState(data["state"]), issued_at=data["issued_at"], expires_at=data["expires_at"],
            token_hash=data["token_hash"], principal=data["principal"], metadata=data.get("metadata") or {},
            fingerprint=data.get("fingerprint") or "",
        )

    def get_session_by_room(self, room_name: str) -> BrowserSenseSession:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM browser_sense_sessions ORDER BY row_id DESC"
            ).fetchall()
        seen: set[str] = set()
        for row in rows:
            session = self._session_from_json(row["payload_json"])
            if session.session_id in seen:
                continue
            seen.add(session.session_id)
            if session.room_name == room_name:
                return session
        raise KeyError(room_name)

    def sessions(self, limit: int = 100) -> list[BrowserSenseSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.payload_json FROM browser_sense_sessions s JOIN (SELECT session_id, MAX(row_id) AS max_id FROM browser_sense_sessions GROUP BY session_id) latest ON s.row_id=latest.max_id ORDER BY s.row_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._session_from_json(row["payload_json"]) for row in rows]

    def _session_from_json(self, raw: str) -> BrowserSenseSession:
        data = json.loads(raw)
        return BrowserSenseSession(
            session_id=data["session_id"], room_name=data["room_name"], participant_identity=data["participant_identity"],
            capabilities=tuple(BrowserSenseCapability(item) for item in data["capabilities"]),
            transports=tuple(BrowserSenseTransport(item) for item in data["transports"]),
            state=BrowserSenseSessionState(data["state"]), issued_at=data["issued_at"], expires_at=data["expires_at"],
            token_hash=data["token_hash"], principal=data["principal"], metadata=data.get("metadata") or {},
            fingerprint=data.get("fingerprint") or "",
        )

    def record_track(self, receipt: BrowserMediaTrackReceipt) -> BrowserMediaTrackReceipt:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_media_tracks(receipt_id,session_id,payload_json,observed_at) VALUES(?,?,?,?)",
                (receipt.receipt_id, receipt.session_id, self._json(asdict(receipt)), receipt.observed_at),
            )
        return receipt

    def record_frame(self, receipt: VisionFrameReceipt) -> VisionFrameReceipt:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_vision_frames(frame_id,session_id,payload_json,observed_at) VALUES(?,?,?,?)",
                (receipt.frame_id, receipt.session_id, self._json(asdict(receipt)), receipt.observed_at),
            )
        return receipt

    def record_turn(self, receipt: BrowserSenseTurnReceipt) -> BrowserSenseTurnReceipt:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_sense_turns(turn_id,session_id,payload_json,completed_at) VALUES(?,?,?,?)",
                (receipt.turn_id, receipt.session_id, self._json(asdict(receipt)), receipt.completed_at),
            )
        return receipt

    def status(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "sessions": int(conn.execute("SELECT COUNT(DISTINCT session_id) FROM browser_sense_sessions").fetchone()[0]),
                "session_events": int(conn.execute("SELECT COUNT(*) FROM browser_sense_sessions").fetchone()[0]),
                "tracks": int(conn.execute("SELECT COUNT(*) FROM browser_media_tracks").fetchone()[0]),
                "vision_frames": int(conn.execute("SELECT COUNT(*) FROM browser_vision_frames").fetchone()[0]),
                "turns": int(conn.execute("SELECT COUNT(*) FROM browser_sense_turns").fetchone()[0]),
            }
