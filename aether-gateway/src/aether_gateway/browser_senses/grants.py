"""Server-authoritative LiveKit grant ledger and revocation.

Every LiveKit participant grant issued for a Senses session is recorded here
with its exact room binding. A device or session revocation invalidates the
session's grants so a bearer token can no longer be presented to the worker
path as a live grant. The ledger is append-only and deterministic so evidence
can be verified independently.

Honest boundary: this is a local authorization ledger. LiveKit-side participant
disconnect is attempted only through ``LiveKitRevokePort`` when the LiveKit
server API is configured and the SDK is available; otherwise the ledger records
``livekit_side=not-wired`` and makes no server-side disconnect claim.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LIVEKIT_GRANT_DEFAULT_TTL_SECONDS = 3600
LIVEKIT_GRANT_MAX_AGE_SECONDS = 86_400

_TERMINAL_GRANT_STATES = {"revoked", "expired"}


class LiveKitGrantError(PermissionError):
    """The grant cannot be used for the requested Senses session."""


class LiveKitRevokePort:
    """Best-effort LiveKit-side participant disconnect.

    When the LiveKit server API is configured and the SDK is available, this
    port removes the participant from the room using the official async
    ``LiveKitAPI.room.remove_participant(RoomParticipantIdentity)`` with a
    bounded timeout and ``aclose()``. Otherwise it honestly reports
    ``livekit_side=not-wired``: the local authorization ledger still revokes
    the grant, but no server-side disconnect is performed or claimed. A
    provider failure/timeout is reported as ``revoke-failed`` with
    ``confirmed=false`` — ``confirmed=true`` is only ever produced by a
    successful LiveKit server call, never inferred.
    """

    REVOKE_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        sdk_loader: Callable[[], Any] | None = None,
    ) -> None:
        self.url = str(url if url is not None else os.environ.get("LIVEKIT_URL") or "").strip()
        self.api_key = str(api_key if api_key is not None else os.environ.get("LIVEKIT_API_KEY") or "").strip()
        self.api_secret = str(api_secret if api_secret is not None else os.environ.get("LIVEKIT_API_SECRET") or "").strip()
        self._sdk_loader = sdk_loader

    def configured(self) -> bool:
        return bool(self.url and self.api_key and self.api_secret)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured(),
            "livekit_side": "wired" if self.configured() else "not-wired",
        }

    def _load_sdk(self) -> Any:
        if self._sdk_loader is not None:
            return self._sdk_loader()
        try:
            from livekit import api
        except ModuleNotFoundError as exc:
            raise RuntimeError("livekit-api sdk missing") from exc
        return api

    @staticmethod
    def _run_coro(coro: Any) -> Any:
        """Run an async coroutine from a sync call site safely.

        Uses ``asyncio.run`` when no loop is running; otherwise runs the
        coroutine on a fresh thread-owned loop so a FastAPI sync route in a
        threadpool (or an async context) can still perform the disconnect.
        """
        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False
        if not running:
            return asyncio.run(coro)
        import threading

        result: dict[str, Any] = {}

        def _runner() -> None:
            result["value"] = asyncio.run(coro)

        thread = threading.Thread(target=_runner, name="livekit-revoke", daemon=True)
        thread.start()
        thread.join()
        return result["value"]

    async def _revoke_async(
        self, *, room_name: str, participant_identity: str, reason: str
    ) -> dict[str, Any]:
        api = self._load_sdk()
        livekit_api = api.LiveKitAPI(self.url, self.api_key, self.api_secret)
        try:
            participant = api.RoomParticipantIdentity(
                room=room_name, identity=participant_identity
            )
            await asyncio.wait_for(
                livekit_api.room.remove_participant(participant),
                timeout=self.REVOKE_TIMEOUT_SECONDS,
            )
            return {
                "livekit_side": "revoked",
                "confirmed": True,
                "reason": str(reason)[:160],
            }
        finally:
            try:
                await asyncio.wait_for(livekit_api.aclose(), timeout=5.0)
            except Exception:  # noqa: BLE001 - closing is best-effort
                pass

    def revoke(
        self,
        *,
        room_name: str,
        participant_identity: str,
        reason: str,
    ) -> dict[str, Any]:
        if not self.configured():
            return {
                "livekit_side": "not-wired",
                "confirmed": False,
                "reason": "livekit not configured; local authorization-ledger revocation only",
            }
        try:
            return self._run_coro(
                self._revoke_async(
                    room_name=room_name,
                    participant_identity=participant_identity,
                    reason=reason,
                )
            )
        except asyncio.TimeoutError:
            return {
                "livekit_side": "revoke-failed",
                "confirmed": False,
                "reason": "livekit revoke timed out",
            }
        except Exception as exc:  # noqa: BLE001 - vendor failures are reported honestly
            return {
                "livekit_side": "revoke-failed",
                "confirmed": False,
                "reason": f"{type(exc).__name__}: {exc}"[:200],
            }


class LiveKitGrantLedger:
    """Append-only ledger of issued LiveKit grants and their revocations."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(timezone.utc))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS livekit_grants (
                    grant_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    room_name TEXT NOT NULL,
                    participant_identity TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_livekit_grants_session
                    ON livekit_grants(session_id, issued_at);
                CREATE TABLE IF NOT EXISTS livekit_grant_events (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    grant_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(grant_id) REFERENCES livekit_grants(grant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_livekit_grant_events
                    ON livekit_grant_events(grant_id, row_id DESC);
                CREATE TRIGGER IF NOT EXISTS livekit_grants_no_update
                    BEFORE UPDATE ON livekit_grants BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS livekit_grants_no_delete
                    BEFORE DELETE ON livekit_grants BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS livekit_grant_events_no_update
                    BEFORE UPDATE ON livekit_grant_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS livekit_grant_events_no_delete
                    BEFORE DELETE ON livekit_grant_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                """
            )

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def _iso(self, value: datetime) -> str:
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def record_grant(
        self,
        *,
        session_id: str,
        room_name: str,
        participant_identity: str,
        participant_token: str,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not session_id.strip() or not room_name.strip() or not participant_identity.strip():
            raise ValueError("LiveKit grant binding identifiers must not be empty")
        if not participant_token:
            raise ValueError("LiveKit grant requires a participant token")
        now = self._now()
        issued_at = self._iso(now)
        expires = (
            expires_at
            or self._iso(now + timedelta(seconds=LIVEKIT_GRANT_DEFAULT_TTL_SECONDS))
        )
        grant_id = f"livekit-grant.{secrets.token_hex(16)}"
        token_hash = hashlib.sha256(participant_token.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO livekit_grants VALUES(?,?,?,?,?,?,?)",
                (
                    grant_id,
                    session_id,
                    room_name,
                    participant_identity,
                    token_hash,
                    issued_at,
                    expires,
                ),
            )
            receipt_id = self._append_event(
                conn,
                grant_id,
                "issued",
                "session-issued",
                now,
                {
                    "session_id": session_id,
                    "room_name": room_name,
                    "participant_identity": participant_identity,
                    **(dict(metadata or {})),
                },
            )
            event = conn.execute(
                "SELECT * FROM livekit_grant_events WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
        return self._public_grant(grant_id, event)

    def _append_event(
        self,
        conn: sqlite3.Connection,
        grant_id: str,
        state: str,
        reason: str,
        recorded_at: datetime,
        payload: dict[str, Any] | None = None,
    ) -> str:
        receipt_id = f"livekit-grant-event.{secrets.token_hex(16)}"
        conn.execute(
            "INSERT INTO livekit_grant_events(receipt_id,grant_id,state,reason,recorded_at,payload_json) VALUES(?,?,?,?,?,?)",
            (
                receipt_id,
                grant_id,
                state,
                reason,
                self._iso(recorded_at),
                self._json(payload or {}),
            ),
        )
        return receipt_id

    def _latest_event(
        self, conn: sqlite3.Connection, grant_id: str
    ) -> sqlite3.Row:
        event = conn.execute(
            "SELECT * FROM livekit_grant_events WHERE grant_id=? ORDER BY row_id DESC LIMIT 1",
            (grant_id,),
        ).fetchone()
        if event is None:
            raise LiveKitGrantError("LiveKit grant has no authoritative state")
        return event

    def _expire_if_needed(
        self, conn: sqlite3.Connection, grant_id: str, event: sqlite3.Row
    ) -> sqlite3.Row:
        if event["state"] in _TERMINAL_GRANT_STATES:
            return event
        row = conn.execute(
            "SELECT expires_at FROM livekit_grants WHERE grant_id=?",
            (grant_id,),
        ).fetchone()
        if row is None:
            raise LiveKitGrantError("unknown LiveKit grant")
        expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
        if self._now() >= expires:
            self._append_event(
                conn, grant_id, "expired", "ttl-expired", self._now()
            )
            event = self._latest_event(conn, grant_id)
        return event

    def revoke_for_session(
        self,
        session_id: str,
        *,
        reason: str,
        revoke_port: LiveKitRevokePort | None = None,
    ) -> list[dict[str, Any]]:
        """Revoke grants for a session without holding a SQLite lock across I/O.

        The candidate grant list is read in a short transaction and the
        connection is closed before the LiveKit revoke call (which may block on
        the network for up to the port timeout). Each grant is then finalized in
        its own short transaction that re-reads the latest state and appends the
        revocation event idempotently, so concurrent grant issue/revoke cannot
        be starved by a held write lock.
        """
        port = revoke_port or LiveKitRevokePort()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT grant_id, room_name, participant_identity FROM livekit_grants WHERE session_id=? ORDER BY issued_at",
                (session_id,),
            ).fetchall()
            candidates = [
                (row["grant_id"], row["room_name"], row["participant_identity"])
                for row in rows
            ]

        revoked: list[dict[str, Any]] = []
        for grant_id, room_name, participant_identity in candidates:
            livekit_side = port.revoke(
                room_name=room_name,
                participant_identity=participant_identity,
                reason=reason,
            )
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                event = self._expire_if_needed(
                    conn, grant_id, self._latest_event(conn, grant_id)
                )
                if event["state"] in _TERMINAL_GRANT_STATES:
                    # Already revoked/expired (e.g. concurrent revoke): skip
                    # idempotently; a revoked grant stays revoked and is not
                    # re-reported as a new revocation.
                    conn.rollback()
                    continue
                receipt_id = self._append_event(
                    conn,
                    grant_id,
                    "revoked",
                    str(reason or "session-revoked")[:160],
                    self._now(),
                    payload={"livekit_side": livekit_side},
                )
                event = conn.execute(
                    "SELECT * FROM livekit_grant_events WHERE receipt_id=?",
                    (receipt_id,),
                ).fetchone()
                revoked.append(self._public_grant(grant_id, event, conn))
                conn.commit()
        return revoked

    def active_for_session(self, session_id: str) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT grant_id FROM livekit_grants WHERE session_id=? ORDER BY issued_at",
                (session_id,),
            ).fetchall()
            for row in rows:
                event = self._expire_if_needed(
                    conn, row["grant_id"], self._latest_event(conn, row["grant_id"])
                )
                if event["state"] not in _TERMINAL_GRANT_STATES:
                    active.append(self._public_grant(row["grant_id"], event, conn))
        return active

    def grant_state(self, grant_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM livekit_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
            if row is None:
                raise LiveKitGrantError("unknown LiveKit grant")
            event = self._expire_if_needed(
                conn, grant_id, self._latest_event(conn, grant_id)
            )
            return self._public_grant(grant_id, event, conn)

    def assert_usable(self, grant_id: str) -> None:
        state = self.grant_state(grant_id)
        if state["state"] != "issued":
            raise LiveKitGrantError(
                f"LiveKit grant is {state['state']} and cannot be used"
            )

    def _public_grant(
        self,
        grant_id: str,
        event: sqlite3.Row,
        _conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        with self._connect() as local_conn:
            row = local_conn.execute(
                "SELECT * FROM livekit_grants WHERE grant_id=?", (grant_id,)
            ).fetchone()
        livekit_side: dict[str, Any] | None = None
        try:
            payload = json.loads(event["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if isinstance(payload, dict) and payload.get("livekit_side"):
            livekit_side = payload["livekit_side"]
        return {
            "grant_id": grant_id,
            "session_id": row["session_id"],
            "room_name": row["room_name"],
            "participant_identity": row["participant_identity"],
            "issued_at": row["issued_at"],
            "expires_at": row["expires_at"],
            "state": event["state"],
            "reason": event["reason"],
            "recorded_at": event["recorded_at"],
            "livekit_side": livekit_side,
        }

    def status(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "grants": int(conn.execute("SELECT COUNT(*) FROM livekit_grants").fetchone()[0]),
                "grant_events": int(conn.execute("SELECT COUNT(*) FROM livekit_grant_events").fetchone()[0]),
            }
