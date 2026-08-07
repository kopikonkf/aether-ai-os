"""Append-only stable turn claims, lifecycle status, and interruption evidence."""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple


class TurnClaimConflict(RuntimeError):
    """The supplied turn ID is already bound to different immutable inputs."""


class TurnClaim(NamedTuple):
    first_claim: bool
    status: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}.{secrets.token_hex(16)}"


def _require_text(value: str | None, name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _require_generation(value: int, name: str = "turn generation") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_sha256(value: str | None, name: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    return normalized


class BrowserSenseTurnLedger:
    """SQLite authority for exactly-once turn claims and hash-only outcomes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS browser_sense_turn_claims (
                    turn_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    request_hash TEXT NOT NULL,
                    retry_of_turn_id TEXT,
                    claimed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_sense_turn_events (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_sense_turn_events_latest
                    ON browser_sense_turn_events(session_id, turn_id, row_id DESC);
                CREATE TABLE IF NOT EXISTS browser_sense_interruptions (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    previous_generation INTEGER NOT NULL,
                    next_generation INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    UNIQUE(session_id, turn_id, previous_generation, next_generation)
                );
                CREATE TRIGGER IF NOT EXISTS browser_sense_turn_claims_no_update
                BEFORE UPDATE ON browser_sense_turn_claims
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_turn_claims_no_delete
                BEFORE DELETE ON browser_sense_turn_claims
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_turn_events_no_update
                BEFORE UPDATE ON browser_sense_turn_events
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_turn_events_no_delete
                BEFORE DELETE ON browser_sense_turn_events
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_interruptions_no_update
                BEFORE UPDATE ON browser_sense_interruptions
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_sense_interruptions_no_delete
                BEFORE DELETE ON browser_sense_interruptions
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                """
            )

    @staticmethod
    def _payload(row: sqlite3.Row) -> dict[str, Any]:
        return dict(json.loads(row["payload_json"]))

    def _latest_status(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        turn_id: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT payload_json FROM browser_sense_turn_events
            WHERE session_id=? AND turn_id=? ORDER BY row_id DESC LIMIT 1
            """,
            (session_id, turn_id),
        ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        return self._payload(row)

    @staticmethod
    def _assert_claim(
        row: sqlite3.Row,
        *,
        session_id: str,
        correlation_id: str,
        generation: int,
        request_hash: str | None = None,
        retry_of_turn_id: str | None = None,
    ) -> None:
        expected = {
            "session_id": session_id,
            "correlation_id": correlation_id,
            "generation": generation,
        }
        if request_hash is not None:
            expected["request_hash"] = request_hash
            expected["retry_of_turn_id"] = retry_of_turn_id
        for name, value in expected.items():
            if row[name] != value:
                raise TurnClaimConflict(f"turn ID is already bound to a different {name}")

    def claim(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
        request_hash: str,
        retry_of_turn_id: str | None,
    ) -> TurnClaim:
        session_id = _require_text(session_id, "turn session ID")
        turn_id = _require_text(turn_id, "turn ID")
        correlation_id = _require_text(correlation_id, "turn correlation ID")
        generation = _require_generation(generation)
        request_hash = _require_sha256(request_hash, "turn request hash")
        retry_of_turn_id = (
            _require_text(retry_of_turn_id, "retry-of turn ID")
            if retry_of_turn_id is not None
            else None
        )
        if retry_of_turn_id == turn_id:
            raise ValueError("a turn cannot retry itself")
        claimed_at = _utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM browser_sense_turn_claims WHERE turn_id=?",
                (turn_id,),
            ).fetchone()
            if existing is not None:
                self._assert_claim(
                    existing,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    generation=generation,
                    request_hash=request_hash,
                    retry_of_turn_id=retry_of_turn_id,
                )
                return TurnClaim(
                    False,
                    self._latest_status(connection, session_id=session_id, turn_id=turn_id),
                )
            if generation != 0:
                raise ValueError("a newly claimed turn must start at generation zero")
            connection.execute(
                """
                INSERT INTO browser_sense_turn_claims(
                    turn_id,session_id,correlation_id,generation,request_hash,
                    retry_of_turn_id,claimed_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    turn_id,
                    session_id,
                    correlation_id,
                    generation,
                    request_hash,
                    retry_of_turn_id,
                    claimed_at,
                ),
            )
            payload = {
                "receipt_id": _new_id("sense-turn-accepted"),
                "session_id": session_id,
                "turn_id": turn_id,
                "correlation_id": correlation_id,
                "generation": generation,
                "state": "accepted",
                "request_hash": request_hash,
                "retry_of_turn_id": retry_of_turn_id,
                "observed_at": claimed_at,
            }
            self._insert_event(connection, payload)
            return TurnClaim(True, payload)

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO browser_sense_turn_events(
                receipt_id,session_id,turn_id,correlation_id,generation,state,
                payload_json,observed_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                payload["receipt_id"],
                payload["session_id"],
                payload["turn_id"],
                payload["correlation_id"],
                payload["generation"],
                payload["state"],
                self._json(payload),
                payload["observed_at"],
            ),
        )

    def _bound_claim(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM browser_sense_turn_claims WHERE turn_id=?",
            (turn_id,),
        ).fetchone()
        if row is None:
            raise KeyError(turn_id)
        self._assert_claim(
            row,
            session_id=session_id,
            correlation_id=correlation_id,
            generation=generation,
        )
        return row

    def complete(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
        response_hash: str,
        terminal_receipt_id: str,
    ) -> dict[str, Any]:
        generation = _require_generation(generation)
        response_hash = _require_sha256(response_hash, "turn response hash")
        terminal_receipt_id = _require_text(terminal_receipt_id, "terminal turn receipt ID")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bound_claim(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                generation=generation,
            )
            latest = self._latest_status(connection, session_id=session_id, turn_id=turn_id)
            if latest["state"] == "completed":
                if (
                    latest["response_hash"] != response_hash
                    or latest["terminal_receipt_id"] != terminal_receipt_id
                ):
                    raise TurnClaimConflict("turn completion does not match its terminal receipt")
                return latest
            if latest["state"] != "accepted":
                raise TurnClaimConflict(f"cannot complete a turn in state {latest['state']}")
            observed_at = _utc_now()
            payload = {
                "receipt_id": _new_id("sense-turn-completed"),
                "session_id": session_id,
                "turn_id": turn_id,
                "correlation_id": correlation_id,
                "generation": generation,
                "state": "completed",
                "response_hash": response_hash,
                "terminal_receipt_id": terminal_receipt_id,
                "observed_at": observed_at,
            }
            self._insert_event(connection, payload)
            return payload

    def fail(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
        failure_code: str,
    ) -> dict[str, Any]:
        generation = _require_generation(generation)
        failure_code = _require_text(failure_code, "turn failure code")[:100]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bound_claim(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                generation=generation,
            )
            latest = self._latest_status(connection, session_id=session_id, turn_id=turn_id)
            if latest["state"] == "failed" and latest["failure_code"] == failure_code:
                return latest
            if latest["state"] != "accepted":
                raise TurnClaimConflict(f"cannot fail a turn in state {latest['state']}")
            observed_at = _utc_now()
            payload = {
                "receipt_id": _new_id("sense-turn-failed"),
                "session_id": session_id,
                "turn_id": turn_id,
                "correlation_id": correlation_id,
                "generation": generation,
                "state": "failed",
                "failure_code": failure_code,
                "observed_at": observed_at,
            }
            self._insert_event(connection, payload)
            return payload

    def interrupt(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        previous_generation: int,
        next_generation: int,
        reason: str,
        provider_cancel_supported: bool,
        provider_cancelled: bool,
        delivered_audio_ms: int | None,
        upstream_cancelled: bool = False,
        browser_audio_stopped: bool = False,
        livekit_control_sent: bool = False,
    ) -> dict[str, Any]:
        previous_generation = _require_generation(previous_generation, "previous generation")
        next_generation = _require_generation(next_generation, "next generation")
        if next_generation != previous_generation + 1:
            raise ValueError("interruption must advance the turn generation exactly once")
        reason = _require_text(reason, "interruption reason")
        if provider_cancelled and not provider_cancel_supported:
            raise ValueError("provider cancellation cannot succeed when unsupported")
        if delivered_audio_ms is not None and (
            isinstance(delivered_audio_ms, bool)
            or not isinstance(delivered_audio_ms, int)
            or delivered_audio_ms < 0
        ):
            raise ValueError("delivered audio duration must be a non-negative integer")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bound_claim(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                generation=previous_generation,
            )
            existing = connection.execute(
                """
                SELECT payload_json FROM browser_sense_interruptions
                WHERE session_id=? AND turn_id=?
                  AND previous_generation=? AND next_generation=?
                """,
                (session_id, turn_id, previous_generation, next_generation),
            ).fetchone()
            if existing is not None:
                payload = self._payload(existing)
                expected = {
                    "reason": reason,
                    "delivered_audio_ms": delivered_audio_ms,
                }
                if any(payload[name] != value for name, value in expected.items()):
                    raise TurnClaimConflict("duplicate interruption changed immutable evidence")
                latest = self._latest_status(
                    connection,
                    session_id=session_id,
                    turn_id=turn_id,
                )
                evidence = {
                    "provider_cancel_supported": bool(
                        latest.get("provider_cancel_supported") or provider_cancel_supported
                    ),
                    "provider_cancelled": bool(
                        latest.get("provider_cancelled") or provider_cancelled
                    ),
                    "browser_audio_stopped": bool(
                        latest.get("browser_audio_stopped") or browser_audio_stopped
                    ),
                    "livekit_control_sent": bool(
                        latest.get("livekit_control_sent") or livekit_control_sent
                    ),
                }
                if all(latest.get(name) == value for name, value in evidence.items()):
                    return latest
                if evidence["provider_cancelled"] and not evidence["provider_cancel_supported"]:
                    raise ValueError("provider cancellation cannot succeed when unsupported")
                observed_at = _utc_now()
                confirmed = {
                    **latest,
                    "receipt_id": _new_id("sense-interruption-evidence"),
                    "interruption_receipt_id": (
                        latest.get("interruption_receipt_id") or payload["receipt_id"]
                    ),
                    **evidence,
                    "evidence_confirmation": True,
                    "late_result_disposition": (
                        "discarded"
                        if latest.get("late_result_disposition") == "discarded"
                        else (
                            "canceled-upstream"
                            if (upstream_cancelled or evidence["provider_cancelled"])
                            else latest["late_result_disposition"]
                        )
                    ),
                    "observed_at": observed_at,
                }
                self._insert_event(connection, confirmed)
                return confirmed
            latest = self._latest_status(connection, session_id=session_id, turn_id=turn_id)
            if latest["generation"] != previous_generation or latest["state"] not in {
                "accepted",
                "completed",
            }:
                raise TurnClaimConflict(
                    f"cannot interrupt turn generation {previous_generation} in state {latest['state']}"
                )
            observed_at = _utc_now()
            receipt_id = _new_id("sense-interruption")
            payload = {
                "receipt_id": receipt_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "correlation_id": correlation_id,
                "generation": next_generation,
                "previous_generation": previous_generation,
                "next_generation": next_generation,
                "state": "interrupted",
                "reason": reason,
                "requested_at": observed_at,
                "audio_silent_at": observed_at,
                "delivered_audio_ms": delivered_audio_ms,
                "provider_cancel_supported": bool(provider_cancel_supported),
                "provider_cancelled": bool(provider_cancelled),
                "browser_audio_stopped": bool(browser_audio_stopped),
                "livekit_control_sent": bool(livekit_control_sent),
                "late_result_disposition": (
                    "canceled-upstream"
                    if (upstream_cancelled or provider_cancelled)
                    else "not-applicable"
                ),
                "observed_at": observed_at,
            }
            connection.execute(
                """
                INSERT INTO browser_sense_interruptions(
                    receipt_id,session_id,turn_id,previous_generation,next_generation,
                    payload_json,observed_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    receipt_id,
                    session_id,
                    turn_id,
                    previous_generation,
                    next_generation,
                    self._json(payload),
                    observed_at,
                ),
            )
            self._insert_event(connection, payload)
            return payload

    def status(self, *, session_id: str, turn_id: str) -> dict[str, Any]:
        session_id = _require_text(session_id, "turn session ID")
        turn_id = _require_text(turn_id, "turn ID")
        with self._connect() as connection:
            return self._latest_status(connection, session_id=session_id, turn_id=turn_id)

    def discard_late_result(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        original_generation: int,
        response_hash: str,
    ) -> dict[str, Any]:
        original_generation = _require_generation(original_generation, "original generation")
        response_hash = _require_sha256(response_hash, "late response hash")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._bound_claim(
                connection,
                session_id=session_id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                generation=original_generation,
            )
            latest = self._latest_status(connection, session_id=session_id, turn_id=turn_id)
            if (
                latest.get("late_result_disposition") == "discarded"
                and latest.get("late_response_hash") == response_hash
            ):
                return latest
            if latest["state"] != "interrupted" or latest["generation"] <= original_generation:
                raise TurnClaimConflict(
                    f"cannot discard a late result while turn is {latest['state']}"
                )
            observed_at = _utc_now()
            payload = {
                **latest,
                "receipt_id": _new_id("sense-late-result-discarded"),
                "interruption_receipt_id": (
                    latest.get("interruption_receipt_id") or latest["receipt_id"]
                ),
                "late_result_disposition": "discarded",
                "late_response_hash": response_hash,
                "observed_at": observed_at,
            }
            self._insert_event(connection, payload)
            return payload

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "claims": int(
                    connection.execute("SELECT COUNT(*) FROM browser_sense_turn_claims").fetchone()[0]
                ),
                "events": int(
                    connection.execute("SELECT COUNT(*) FROM browser_sense_turn_events").fetchone()[0]
                ),
                "interruptions": int(
                    connection.execute("SELECT COUNT(*) FROM browser_sense_interruptions").fetchone()[0]
                ),
            }
