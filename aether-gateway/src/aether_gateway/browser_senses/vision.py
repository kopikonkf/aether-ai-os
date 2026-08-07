"""Server-authoritative Senses v1 consent leases and ephemeral frame lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import struct
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BOUNDED_CAPTURE_INTERVAL_SECONDS = 15
BOUNDED_CONSENT_LEASE_SECONDS = 15 * 60
ONE_SHOT_CONSENT_LEASE_SECONDS = 2 * 60
ORPHAN_FRAME_MAX_AGE_SECONDS = 5 * 60
CAPTURE_CLOCK_SKEW_SECONDS = 30
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 16_777_216

_SOURCES = {"camera": "camera", "screen": "screen-share"}
_MODES = {"one-shot", "bounded"}
_TERMINAL_CONSENT_STATES = {"revoked", "expired"}
_TERMINAL_FRAME_STATES = {"deleted", "swept", "deletion-failed", "stage-failed"}
_PROVEN_DELETION_STATES = {"deleted", "swept"}


class VisionConsentError(PermissionError):
    """The requested transmission is not covered by an active exact lease."""


class VisionFrameValidationError(ValueError):
    """Raw frame bytes do not match the bounded v1 image contract."""


class VisionDeletionError(RuntimeError):
    """Raw working data could not be proven deleted."""


def _new_id(prefix: str) -> str:
    return f"{prefix}.{secrets.token_hex(16)}"


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise VisionFrameValidationError("capture timestamp must be ISO-8601 UTC") from exc
    if parsed.tzinfo is None:
        raise VisionFrameValidationError("capture timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    if len(raw) < 4 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        raise VisionFrameValidationError("JPEG signature is invalid")
    position = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while position + 4 <= len(raw):
        if raw[position] != 0xFF:
            position += 1
            continue
        while position < len(raw) and raw[position] == 0xFF:
            position += 1
        if position >= len(raw):
            break
        marker = raw[position]
        position += 1
        if marker in {0x01, *range(0xD0, 0xDA)}:
            continue
        if position + 2 > len(raw):
            break
        segment_length = int.from_bytes(raw[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > len(raw):
            raise VisionFrameValidationError("JPEG segment structure is invalid")
        if marker in start_of_frame:
            if segment_length < 7:
                raise VisionFrameValidationError("JPEG dimensions are invalid")
            height = int.from_bytes(raw[position + 3:position + 5], "big")
            width = int.from_bytes(raw[position + 5:position + 7], "big")
            return width, height
        position += segment_length
    raise VisionFrameValidationError("JPEG dimensions are missing")


def _webp_dimensions(raw: bytes) -> tuple[int, int]:
    if len(raw) < 30 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise VisionFrameValidationError("WebP signature is invalid")
    chunk = raw[12:16]
    if chunk == b"VP8X":
        return (
            1 + int.from_bytes(raw[24:27], "little"),
            1 + int.from_bytes(raw[27:30], "little"),
        )
    if chunk == b"VP8L" and raw[20] == 0x2F:
        bits = int.from_bytes(raw[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 " and len(raw) >= 30 and raw[23:26] == b"\x9d\x01\x2a":
        return (
            int.from_bytes(raw[26:28], "little") & 0x3FFF,
            int.from_bytes(raw[28:30], "little") & 0x3FFF,
        )
    raise VisionFrameValidationError("WebP dimensions are missing")


def validate_image(
    raw: bytes,
    *,
    content_type: str,
    maximum_frame_bytes: int,
    declared_width: int | None,
    declared_height: int | None,
) -> tuple[int, int]:
    if not raw or len(raw) > maximum_frame_bytes:
        raise VisionFrameValidationError(
            f"vision frame must be 1..{maximum_frame_bytes} bytes"
        )
    if content_type == "image/png":
        if (
            len(raw) < 29
            or raw[:8] != b"\x89PNG\r\n\x1a\n"
            or raw[12:16] != b"IHDR"
        ):
            raise VisionFrameValidationError("PNG signature is invalid")
        width, height = struct.unpack(">II", raw[16:24])
    elif content_type == "image/jpeg":
        width, height = _jpeg_dimensions(raw)
    elif content_type == "image/webp":
        width, height = _webp_dimensions(raw)
    else:
        raise VisionFrameValidationError("unsupported vision frame content type")
    if (
        width < 1
        or height < 1
        or width > MAX_IMAGE_DIMENSION
        or height > MAX_IMAGE_DIMENSION
        or width * height > MAX_IMAGE_PIXELS
    ):
        raise VisionFrameValidationError("vision frame dimensions exceed the bounded policy")
    if declared_width != width or declared_height != height:
        raise VisionFrameValidationError("declared vision frame dimensions do not match content")
    return width, height


class VisionLifecycle:
    """Append-only lease/evidence ledger with raw bytes in a temporary workspace only."""

    def __init__(
        self,
        path: Path,
        frames_root: Path,
        *,
        maximum_frame_bytes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.frames_root = frames_root
        self.maximum_frame_bytes = maximum_frame_bytes
        self._now = now or (lambda: datetime.now(timezone.utc))
        path.parent.mkdir(parents=True, exist_ok=True)
        frames_root.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS vision_consents (
                    consent_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    capture_interval_seconds INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_vision_consents_session_source
                    ON vision_consents(session_id, source, granted_at);
                CREATE TABLE IF NOT EXISTS vision_consent_events (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    consent_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(consent_id) REFERENCES vision_consents(consent_id)
                );
                CREATE INDEX IF NOT EXISTS idx_vision_consent_events
                    ON vision_consent_events(consent_id, row_id DESC);
                CREATE TABLE IF NOT EXISTS vision_frames (
                    frame_id TEXT PRIMARY KEY,
                    consent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    ephemeral_handle TEXT NOT NULL,
                    UNIQUE(consent_id, sequence_number),
                    FOREIGN KEY(consent_id) REFERENCES vision_consents(consent_id)
                );
                CREATE TABLE IF NOT EXISTS vision_frame_events (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    receipt_id TEXT NOT NULL UNIQUE,
                    frame_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(frame_id) REFERENCES vision_frames(frame_id)
                );
                CREATE INDEX IF NOT EXISTS idx_vision_frame_events
                    ON vision_frame_events(frame_id, row_id DESC);
                CREATE TRIGGER IF NOT EXISTS vision_consents_no_update
                    BEFORE UPDATE ON vision_consents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_consents_no_delete
                    BEFORE DELETE ON vision_consents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_consent_events_no_update
                    BEFORE UPDATE ON vision_consent_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_consent_events_no_delete
                    BEFORE DELETE ON vision_consent_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_frames_no_update
                    BEFORE UPDATE ON vision_frames BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_frames_no_delete
                    BEFORE DELETE ON vision_frames BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_frame_events_no_update
                    BEFORE UPDATE ON vision_frame_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS vision_frame_events_no_delete
                    BEFORE DELETE ON vision_frame_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                """
            )

    @staticmethod
    def _latest_consent_event(
        conn: sqlite3.Connection, consent_id: str
    ) -> sqlite3.Row:
        event = conn.execute(
            "SELECT * FROM vision_consent_events WHERE consent_id=? ORDER BY row_id DESC LIMIT 1",
            (consent_id,),
        ).fetchone()
        if event is None:
            raise VisionConsentError("vision consent lease has no authoritative state")
        return event

    @staticmethod
    def _append_consent_event(
        conn: sqlite3.Connection,
        consent_id: str,
        state: str,
        reason: str,
        recorded_at: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        receipt_id = _new_id("vision-consent-event")
        conn.execute(
            "INSERT INTO vision_consent_events(receipt_id,consent_id,state,reason,recorded_at,payload_json) VALUES(?,?,?,?,?,?)",
            (receipt_id, consent_id, state, reason, recorded_at, _json(payload or {})),
        )
        return receipt_id

    @staticmethod
    def _public_consent(row: sqlite3.Row, event: sqlite3.Row) -> dict[str, Any]:
        return {
            "consent_id": row["consent_id"],
            "receipt_id": event["receipt_id"],
            "session_id": row["session_id"],
            "source": row["source"],
            "mode": row["mode"],
            "state": event["state"],
            "granted_at": row["granted_at"],
            "expires_at": row["expires_at"],
            "capture_interval_seconds": row["capture_interval_seconds"],
            "recorded_at": event["recorded_at"],
            "reason": event["reason"],
        }

    def _expire_if_needed(
        self, conn: sqlite3.Connection, row: sqlite3.Row, event: sqlite3.Row
    ) -> sqlite3.Row:
        if event["state"] == "active" and self._now() >= _parse(row["expires_at"]):
            self._append_consent_event(
                conn, row["consent_id"], "expired", "lease-expired", _iso(self._now())
            )
            event = self._latest_consent_event(conn, row["consent_id"])
        return event

    def grant_consent(
        self,
        *,
        session_id: str,
        device_id: str,
        source: str,
        mode: str,
        capabilities: Iterable[str],
    ) -> dict[str, Any]:
        if source not in _SOURCES:
            raise VisionConsentError("vision consent source must be camera or screen")
        if mode not in _MODES:
            raise VisionConsentError("vision transmission requires one-shot or bounded consent")
        if _SOURCES[source] not in set(capabilities):
            raise VisionConsentError(f"{_SOURCES[source]} capability was not granted")
        now = self._now()
        duration = (
            BOUNDED_CONSENT_LEASE_SECONDS
            if mode == "bounded"
            else ONE_SHOT_CONSENT_LEASE_SECONDS
        )
        consent_id = _new_id("vision-consent")
        recorded_at = _iso(now)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active_rows = conn.execute(
                "SELECT * FROM vision_consents WHERE session_id=? AND device_id=? AND source=? ORDER BY granted_at",
                (session_id, device_id, source),
            ).fetchall()
            for active in active_rows:
                latest = self._expire_if_needed(
                    conn, active, self._latest_consent_event(conn, active["consent_id"])
                )
                if latest["state"] == "active":
                    self._append_consent_event(
                        conn,
                        active["consent_id"],
                        "revoked",
                        "superseded-by-new-lease",
                        recorded_at,
                    )
            conn.execute(
                "INSERT INTO vision_consents VALUES(?,?,?,?,?,?,?,?)",
                (
                    consent_id,
                    session_id,
                    device_id,
                    source,
                    mode,
                    recorded_at,
                    _iso(now + timedelta(seconds=duration)),
                    BOUNDED_CAPTURE_INTERVAL_SECONDS if mode == "bounded" else None,
                ),
            )
            receipt_id = self._append_consent_event(
                conn, consent_id, "active", "explicit-user-gesture", recorded_at
            )
            row = conn.execute(
                "SELECT * FROM vision_consents WHERE consent_id=?", (consent_id,)
            ).fetchone()
            event = conn.execute(
                "SELECT * FROM vision_consent_events WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return self._public_consent(row, event)

    def _bound_active_consent(
        self,
        conn: sqlite3.Connection,
        *,
        consent_id: str,
        session_id: str,
        device_id: str,
        source: str,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        row = conn.execute(
            "SELECT * FROM vision_consents WHERE consent_id=?", (consent_id,)
        ).fetchone()
        if row is None:
            raise VisionConsentError("unknown vision consent lease")
        if row["session_id"] != session_id:
            raise VisionConsentError("vision consent session binding mismatch")
        if row["device_id"] != device_id:
            raise VisionConsentError("vision consent device binding mismatch")
        if row["source"] != source:
            raise VisionConsentError("vision consent source binding mismatch")
        event = self._expire_if_needed(
            conn, row, self._latest_consent_event(conn, consent_id)
        )
        if event["state"] != "active":
            raise VisionConsentError(f"vision consent lease is {event['state']}")
        return row, event

    def revoke_consent(
        self,
        *,
        session_id: str,
        device_id: str,
        consent_id: str,
        reason: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM vision_consents WHERE consent_id=?", (consent_id,)
            ).fetchone()
            if row is None:
                raise VisionConsentError("unknown vision consent lease")
            if row["session_id"] != session_id or row["device_id"] != device_id:
                raise VisionConsentError("vision consent device binding mismatch")
            event = self._expire_if_needed(
                conn, row, self._latest_consent_event(conn, consent_id)
            )
            if event["state"] not in _TERMINAL_CONSENT_STATES:
                receipt_id = self._append_consent_event(
                    conn,
                    consent_id,
                    "revoked",
                    str(reason or "explicit-stop")[:160],
                    _iso(self._now()),
                )
                event = conn.execute(
                    "SELECT * FROM vision_consent_events WHERE receipt_id=?",
                    (receipt_id,),
                ).fetchone()
        return self._public_consent(row, event)

    def revoke_session(self, session_id: str, *, reason: str) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT * FROM vision_consents WHERE session_id=? ORDER BY granted_at",
                (session_id,),
            ).fetchall()
            for row in rows:
                event = self._expire_if_needed(
                    conn, row, self._latest_consent_event(conn, row["consent_id"])
                )
                if event["state"] == "active":
                    receipt_id = self._append_consent_event(
                        conn,
                        row["consent_id"],
                        "revoked",
                        str(reason or "session-closed")[:160],
                        _iso(self._now()),
                    )
                    event = conn.execute(
                        "SELECT * FROM vision_consent_events WHERE receipt_id=?",
                        (receipt_id,),
                    ).fetchone()
                    receipts.append(self._public_consent(row, event))
        return receipts

    def accept_frame(
        self,
        *,
        session_id: str,
        device_id: str,
        consent_id: str,
        source: str,
        sequence_number: int,
        captured_at: str,
        content_type: str,
        raw: bytes,
        declared_width: int | None,
        declared_height: int | None,
        prompt: str,
        turn_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        width, height = validate_image(
            raw,
            content_type=content_type,
            maximum_frame_bytes=self.maximum_frame_bytes,
            declared_width=declared_width,
            declared_height=declared_height,
        )
        if not isinstance(sequence_number, int) or sequence_number < 1:
            raise VisionFrameValidationError("vision frame sequence must be a positive integer")
        capture_time = _parse(captured_at)
        if abs((self._now() - capture_time).total_seconds()) > CAPTURE_CLOCK_SKEW_SECONDS:
            raise VisionFrameValidationError("vision capture timestamp is outside the allowed clock window")
        digest = hashlib.sha256(raw).hexdigest()
        normalized_prompt = str(prompt or "").strip()
        prompt_hash = hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest()
        frame_id = _new_id("vision-frame")
        accepted_at = _iso(self._now())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            consent, _ = self._bound_active_consent(
                conn,
                consent_id=consent_id,
                session_id=session_id,
                device_id=device_id,
                source=source,
            )
            previous = conn.execute(
                "SELECT sequence_number,captured_at FROM vision_frames WHERE consent_id=? ORDER BY sequence_number DESC LIMIT 1",
                (consent_id,),
            ).fetchone()
            expected_sequence = 1 if previous is None else int(previous["sequence_number"]) + 1
            if sequence_number != expected_sequence:
                raise VisionConsentError(
                    f"vision frame sequence must be exactly {expected_sequence}"
                )
            if consent["mode"] == "one-shot" and sequence_number != 1:
                raise VisionConsentError("one-shot vision consent was already consumed")
            if previous is not None and (
                capture_time - _parse(previous["captured_at"])
            ).total_seconds() < BOUNDED_CAPTURE_INTERVAL_SECONDS:
                raise VisionConsentError("bounded vision requires a 15-second capture interval")
            conn.execute(
                "INSERT INTO vision_frames VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    frame_id,
                    consent_id,
                    session_id,
                    source,
                    sequence_number,
                    _iso(capture_time),
                    accepted_at,
                    digest,
                    len(raw),
                    content_type,
                    width,
                    height,
                    prompt_hash,
                    turn_id,
                    correlation_id,
                    frame_id,
                ),
            )
            frame_receipt_id = _new_id("vision-frame-event")
            conn.execute(
                "INSERT INTO vision_frame_events(receipt_id,frame_id,state,reason,recorded_at,payload_json) VALUES(?,?,?,?,?,?)",
                (
                    frame_receipt_id,
                    frame_id,
                    "accepted",
                    "validated-keyframe",
                    accepted_at,
                    _json({"transport": "http-keyframe"}),
                ),
            )
            if consent["mode"] == "one-shot":
                self._append_consent_event(
                    conn,
                    consent_id,
                    "revoked",
                    "one-shot-consumed",
                    accepted_at,
                    {"frame_id": frame_id},
                )
        path = self.frames_root / f"{frame_id}.raw"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            self._record_frame_terminal(frame_id, "stage-failed", "working-file-write-failed")
            raise
        return {
            "frame_id": frame_id,
            "receipt_id": frame_receipt_id,
            "session_id": session_id,
            "consent_id": consent_id,
            "source": source,
            "sequence_number": sequence_number,
            "captured_at": _iso(capture_time),
            "accepted_at": accepted_at,
            "content_hash": digest,
            "byte_count": len(raw),
            "content_type": content_type,
            "width": width,
            "height": height,
            "prompt_hash": prompt_hash,
            "turn_id": turn_id,
            "correlation_id": correlation_id,
            "ephemeral_handle": frame_id,
            "_working_path": str(path),
        }

    def _record_frame_terminal(self, frame_id: str, state: str, reason: str) -> str:
        if state not in _TERMINAL_FRAME_STATES:
            raise ValueError("unknown vision frame terminal state")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = conn.execute(
                "SELECT * FROM vision_frame_events WHERE frame_id=? ORDER BY row_id DESC LIMIT 1",
                (frame_id,),
            ).fetchone()
            if latest is None:
                raise KeyError(frame_id)
            if latest["state"] in _PROVEN_DELETION_STATES:
                return str(latest["receipt_id"])
            receipt_id = _new_id("vision-frame-event")
            conn.execute(
                "INSERT INTO vision_frame_events(receipt_id,frame_id,state,reason,recorded_at,payload_json) VALUES(?,?,?,?,?,?)",
                (receipt_id, frame_id, state, reason, _iso(self._now()), "{}"),
            )
        return receipt_id

    def delete_frame(
        self,
        frame_id: str,
        *,
        reason: str,
        outcome: str = "deleted",
    ) -> dict[str, Any]:
        path = self.frames_root / f"{frame_id}.raw"
        try:
            path.unlink(missing_ok=True)
            if path.exists():
                raise OSError("working frame still exists after deletion")
        except OSError as exc:
            self._record_frame_terminal(frame_id, "deletion-failed", type(exc).__name__)
            raise VisionDeletionError("raw vision frame deletion could not be proven") from exc
        self._record_frame_terminal(frame_id, outcome, str(reason or "turn-terminal")[:160])
        return self.frame_receipt(frame_id)

    def frame_receipt(self, frame_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            frame = conn.execute(
                "SELECT * FROM vision_frames WHERE frame_id=?", (frame_id,)
            ).fetchone()
            if frame is None:
                raise KeyError(frame_id)
            latest = conn.execute(
                "SELECT * FROM vision_frame_events WHERE frame_id=? ORDER BY row_id DESC LIMIT 1",
                (frame_id,),
            ).fetchone()
        return {
            "frame_id": frame["frame_id"],
            "receipt_id": latest["receipt_id"],
            "session_id": frame["session_id"],
            "consent_id": frame["consent_id"],
            "source": frame["source"],
            "sequence_number": int(frame["sequence_number"]),
            "captured_at": frame["captured_at"],
            "accepted_at": frame["accepted_at"],
            "content_hash": frame["content_hash"],
            "byte_count": int(frame["byte_count"]),
            "content_type": frame["content_type"],
            "width": int(frame["width"]),
            "height": int(frame["height"]),
            "prompt_hash": frame["prompt_hash"],
            "turn_id": frame["turn_id"],
            "correlation_id": frame["correlation_id"],
            "ephemeral_handle": frame["ephemeral_handle"],
            "deletion_outcome": latest["state"] if latest["state"] != "accepted" else None,
            "deleted_at": latest["recorded_at"] if latest["state"] != "accepted" else None,
            "deletion_reason": latest["reason"] if latest["state"] != "accepted" else None,
        }

    def sweep_orphans(
        self, *, maximum_age_seconds: int = ORPHAN_FRAME_MAX_AGE_SECONDS
    ) -> int:
        cutoff = self._now().timestamp() - maximum_age_seconds
        swept = 0
        for path in self.frames_root.glob("vision-frame.*.raw"):
            try:
                if path.stat().st_mtime > cutoff:
                    continue
                frame_id = path.name[:-4]
                self.delete_frame(frame_id, reason="crash-orphan-sweeper", outcome="swept")
                swept += 1
            except FileNotFoundError:
                continue
        return swept

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "consents": int(conn.execute("SELECT COUNT(*) FROM vision_consents").fetchone()[0]),
                "consent_events": int(conn.execute("SELECT COUNT(*) FROM vision_consent_events").fetchone()[0]),
                "frames": int(conn.execute("SELECT COUNT(*) FROM vision_frames").fetchone()[0]),
                "frame_events": int(conn.execute("SELECT COUNT(*) FROM vision_frame_events").fetchone()[0]),
                "raw_frames_present": sum(1 for _ in self.frames_root.glob("vision-frame.*.raw")),
            }
