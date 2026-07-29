"""Provider-neutral conversation session stores."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from aether.utils.time import utc_now

Message = Mapping[str, Any]


@runtime_checkable
class ConversationStore(Protocol):
    async def get(self, session_id: str) -> Sequence[Message]: ...

    async def append(self, session_id: str, *messages: Message) -> None: ...

    async def clear(self, session_id: str) -> None: ...


class InMemoryConversationStore(ConversationStore):
    """Bounded process-local context retained for tests and ephemeral workers."""

    def __init__(self, *, max_messages: int = 24) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2")
        self.max_messages = max_messages
        self._messages: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> Sequence[Message]:
        async with self._lock:
            return tuple(deepcopy(self._messages.get(session_id, [])))

    async def append(self, session_id: str, *messages: Message) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        async with self._lock:
            history = self._messages.setdefault(session_id, [])
            history.extend(dict(deepcopy(message)) for message in messages)
            if len(history) > self.max_messages:
                self._messages[session_id] = history[-self.max_messages :]

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._messages.pop(session_id, None)


class SQLiteConversationStore(ConversationStore):
    """Durable bounded cognitive sessions shared across process restarts."""

    def __init__(self, path: Path, *, max_messages: int = 48) -> None:
        if max_messages < 2:
            raise ValueError("max_messages must be at least 2")
        self.path = path
        self.max_messages = max_messages
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
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
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cleared_at TEXT
                );
                CREATE TABLE IF NOT EXISTS session_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_session_messages_lookup
                    ON session_messages(session_id, id DESC);
                """
            )

    async def get(self, session_id: str) -> Sequence[Message]:
        if not session_id.strip():
            return ()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content_json FROM (
                    SELECT id, role, content_json
                    FROM session_messages
                    WHERE session_id = ?
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, self.max_messages),
            ).fetchall()
        return tuple({"role": row["role"], **json.loads(row["content_json"])} for row in rows)

    async def append(self, session_id: str, *messages: Message) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        now = utc_now()
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO sessions(session_id, created_at, updated_at, cleared_at)
                       VALUES (?, ?, ?, NULL)
                       ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at, cleared_at=NULL""",
                    (session_id, now, now),
                )
                for message in messages:
                    data = dict(deepcopy(message))
                    role = str(data.pop("role", "unknown"))
                    conn.execute(
                        "INSERT INTO session_messages(session_id, role, content_json, created_at) VALUES (?, ?, ?, ?)",
                        (session_id, role, json.dumps(data, ensure_ascii=False, default=str), now),
                    )
                conn.execute(
                    """DELETE FROM session_messages WHERE session_id = ? AND id NOT IN (
                           SELECT id FROM session_messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
                       )""",
                    (session_id, session_id, self.max_messages),
                )

    async def clear(self, session_id: str) -> None:
        now = utc_now()
        async with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM session_messages WHERE session_id = ?", (session_id,))
                conn.execute("UPDATE sessions SET updated_at = ?, cleared_at = ? WHERE session_id = ?", (now, now, session_id))

    async def list_sessions(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT s.session_id, s.created_at, s.updated_at, s.cleared_at,
                          COUNT(m.id) AS message_count
                   FROM sessions s LEFT JOIN session_messages m ON m.session_id=s.session_id
                   GROUP BY s.session_id ORDER BY s.updated_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return tuple(dict(row) for row in rows)
