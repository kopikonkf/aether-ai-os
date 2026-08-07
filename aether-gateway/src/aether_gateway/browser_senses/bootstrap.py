"""Pairing, device credentials, and HttpOnly browser-sense session bindings."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aether.contracts import EventType
from aether.events import EventBus
from aether.utils.ids import new_id
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature


class BootstrapError(RuntimeError):
    """Base class for protocol failures safe to translate at the HTTP seam."""


class BootstrapRateLimitError(BootstrapError):
    pass


class BootstrapStateError(BootstrapError):
    pass


class DeviceCredentialError(PermissionError):
    pass


class SessionCredentialError(PermissionError):
    pass


_HEX_256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_CAPABILITIES = {"text", "microphone", "speaker", "camera", "screen-share"}
_ALLOWED_MODES = {"browser", "pwa", "session-only"}


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


class BrowserSenseBootstrapService:
    """Durable, replay-safe implementation of Senses v1 bootstrap section 6."""

    pairing_ttl_seconds = 120
    source_window_seconds = 600
    source_limit = 5
    global_window_seconds = 3600
    global_limit = 30
    device_absolute_seconds = 30 * 24 * 3600
    device_idle_seconds = 7 * 24 * 3600
    session_absolute_seconds = 3600
    session_idle_seconds = 15 * 60
    challenge_ttl_seconds = 60

    def __init__(
        self,
        path: Path,
        *,
        event_bus: EventBus,
        secret: str,
        allowed_origin: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("browser sense bootstrap secret must be at least 32 bytes")
        origin = allowed_origin.strip().rstrip("/")
        if not origin.startswith("https://"):
            raise ValueError("browser sense origin must be HTTPS")
        self.path = path
        self.event_bus = event_bus
        self._secret = secret.encode("utf-8")
        self.allowed_origin = origin
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
                CREATE TABLE IF NOT EXISTS browser_pairing_requests (
                    bootstrap_id TEXT PRIMARY KEY,
                    client_proof_hash TEXT NOT NULL,
                    verifier_hash TEXT NOT NULL,
                    public_key_jwk_json TEXT NOT NULL,
                    public_key_hash TEXT NOT NULL,
                    device_label TEXT NOT NULL,
                    client_mode TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    source_hint TEXT NOT NULL,
                    confirmation_code TEXT NOT NULL,
                    exchange_challenge TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_browser_pairing_source_time
                    ON browser_pairing_requests(source_hash, created_at);
                CREATE TABLE IF NOT EXISTS browser_pairing_events (
                    event_id TEXT PRIMARY KEY,
                    bootstrap_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(bootstrap_id) REFERENCES browser_pairing_requests(bootstrap_id)
                );
                CREATE INDEX IF NOT EXISTS idx_browser_pairing_events
                    ON browser_pairing_events(bootstrap_id, recorded_at);
                CREATE TABLE IF NOT EXISTS browser_paired_devices (
                    device_id TEXT PRIMARY KEY,
                    bootstrap_id TEXT NOT NULL UNIQUE,
                    principal TEXT NOT NULL,
                    public_key_jwk_json TEXT NOT NULL,
                    credential_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(bootstrap_id) REFERENCES browser_pairing_requests(bootstrap_id)
                );
                CREATE TABLE IF NOT EXISTS browser_device_events (
                    event_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES browser_paired_devices(device_id)
                );
                CREATE INDEX IF NOT EXISTS idx_browser_device_events
                    ON browser_device_events(device_id, recorded_at);
                CREATE TABLE IF NOT EXISTS browser_session_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES browser_paired_devices(device_id)
                );
                CREATE TABLE IF NOT EXISTS browser_session_challenge_events (
                    event_id TEXT PRIMARY KEY,
                    challenge_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(challenge_id) REFERENCES browser_session_challenges(challenge_id)
                );
                CREATE TABLE IF NOT EXISTS browser_session_bindings (
                    session_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    credential_hash TEXT NOT NULL UNIQUE,
                    csrf_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    FOREIGN KEY(device_id) REFERENCES browser_paired_devices(device_id)
                );
                CREATE TABLE IF NOT EXISTS browser_session_binding_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES browser_session_bindings(session_id)
                );
                CREATE INDEX IF NOT EXISTS idx_browser_session_binding_events
                    ON browser_session_binding_events(session_id, recorded_at);
                CREATE TRIGGER IF NOT EXISTS browser_pairing_events_no_update
                    BEFORE UPDATE ON browser_pairing_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_pairing_events_no_delete
                    BEFORE DELETE ON browser_pairing_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_pairing_requests_no_update
                    BEFORE UPDATE ON browser_pairing_requests BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_pairing_requests_no_delete
                    BEFORE DELETE ON browser_pairing_requests BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_device_events_no_update
                    BEFORE UPDATE ON browser_device_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_device_events_no_delete
                    BEFORE DELETE ON browser_device_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_paired_devices_no_update
                    BEFORE UPDATE ON browser_paired_devices BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_paired_devices_no_delete
                    BEFORE DELETE ON browser_paired_devices BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_challenges_no_update
                    BEFORE UPDATE ON browser_session_challenges BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_challenges_no_delete
                    BEFORE DELETE ON browser_session_challenges BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_challenge_events_no_update
                    BEFORE UPDATE ON browser_session_challenge_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_challenge_events_no_delete
                    BEFORE DELETE ON browser_session_challenge_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_bindings_no_update
                    BEFORE UPDATE ON browser_session_bindings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_bindings_no_delete
                    BEFORE DELETE ON browser_session_bindings BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_binding_events_no_update
                    BEFORE UPDATE ON browser_session_binding_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS browser_session_binding_events_no_delete
                    BEFORE DELETE ON browser_session_binding_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
                """
            )

    def _digest(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _source_hash(self, source: str) -> str:
        return hmac.new(
            self._secret, f"source:{source}".encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _source_hint(source: str) -> str:
        candidate = source.strip()
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            return "network-unavailable"
        if address.version == 4:
            octets = candidate.split(".")
            return ".".join((*octets[:3], "x"))
        return f"{':'.join(address.exploded.split(':')[:4])}:…"

    @staticmethod
    def _public_key(jwk: Mapping[str, Any]) -> ec.EllipticCurvePublicKey:
        key_ops = jwk.get("key_ops")
        if (
            jwk.get("kty") != "EC"
            or jwk.get("crv") != "P-256"
            or "d" in jwk
            or (key_ops is not None and key_ops != ["verify"])
            or len(_canonical(jwk)) > 2048
        ):
            raise ValueError("device public key must be a P-256 EC JWK")
        try:
            x = _unb64url(str(jwk["x"]))
            y = _unb64url(str(jwk["y"]))
            if len(x) != 32 or len(y) != 32:
                raise ValueError
            return ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
            ).public_key()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid P-256 device public key") from exc

    @classmethod
    def _verify_signature(
        cls, jwk: Mapping[str, Any], challenge: str, signature: str
    ) -> None:
        try:
            raw = _unb64url(signature)
            if len(raw) == 64:
                raw = encode_dss_signature(
                    int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
                )
            cls._public_key(jwk).verify(
                raw, challenge.encode("utf-8"), ec.ECDSA(hashes.SHA256())
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise PermissionError("invalid device proof signature") from exc

    @staticmethod
    def _latest_pairing_event(
        conn: sqlite3.Connection, bootstrap_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM browser_pairing_events WHERE bootstrap_id=? ORDER BY rowid DESC LIMIT 1",
            (bootstrap_id,),
        ).fetchone()

    @staticmethod
    def _latest_device_event(
        conn: sqlite3.Connection, device_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM browser_device_events WHERE device_id=? ORDER BY rowid DESC LIMIT 1",
            (device_id,),
        ).fetchone()

    @staticmethod
    def _latest_challenge_event(
        conn: sqlite3.Connection, challenge_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM browser_session_challenge_events WHERE challenge_id=? ORDER BY rowid DESC LIMIT 1",
            (challenge_id,),
        ).fetchone()

    @staticmethod
    def _latest_session_event(
        conn: sqlite3.Connection, session_id: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM browser_session_binding_events WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
            (session_id,),
        ).fetchone()

    def _emit(
        self, event_type: str, payload: dict[str, Any], *, severity: str = "info"
    ) -> None:
        self.event_bus.emit(
            event_type,
            actor="aether.browser-senses.bootstrap",
            payload=payload,
            severity=severity,
        )

    def request_pairing(
        self,
        *,
        public_key_jwk: Mapping[str, Any],
        verifier_hash: str,
        device_label: str,
        client_mode: str,
        capabilities: Sequence[str],
        source: str,
    ) -> dict[str, Any]:
        now = self._now()
        label = device_label.strip()
        mode = client_mode.strip().casefold()
        normalized_capabilities = tuple(
            dict.fromkeys(str(item).strip() for item in capabilities)
        )
        normalized_verifier_hash = verifier_hash.strip().casefold()
        if not label or len(label) > 120:
            raise ValueError("device label must be 1..120 characters")
        if mode not in _ALLOWED_MODES:
            raise ValueError("unsupported browser sense client mode")
        if not normalized_capabilities or any(
            item not in _ALLOWED_CAPABILITIES for item in normalized_capabilities
        ):
            raise ValueError("unsupported browser sense capability")
        if not _HEX_256.fullmatch(normalized_verifier_hash):
            raise ValueError("verifier hash must be lowercase SHA-256 hex")
        self._public_key(public_key_jwk)
        public_jwk_json = _canonical(public_key_jwk)
        public_key_hash = self._digest(public_jwk_json)
        source_hash = self._source_hash(source)
        source_cutoff = _iso(now - timedelta(seconds=self.source_window_seconds))
        global_cutoff = _iso(now - timedelta(seconds=self.global_window_seconds))
        bootstrap_id = new_id("sense-bootstrap")
        client_proof = _b64url(secrets.token_bytes(32))
        nonce = _b64url(secrets.token_bytes(32))
        challenge = "\n".join(
            (
                "aether.senses.pairing.v1",
                f"bootstrap_id={bootstrap_id}",
                f"origin={self.allowed_origin}",
                f"verifier_sha256={normalized_verifier_hash}",
                f"public_key_sha256={public_key_hash}",
                f"nonce={nonce}",
            )
        )
        created_at = _iso(now)
        expires_at = _iso(now + timedelta(seconds=self.pairing_ttl_seconds))
        confirmation_code = f"{secrets.randbelow(1_000_000):06d}"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM browser_pairing_requests WHERE source_hash=? AND created_at>=?",
                    (source_hash, source_cutoff),
                ).fetchone()[0]
            )
            global_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM browser_pairing_requests WHERE created_at>=?",
                    (global_cutoff,),
                ).fetchone()[0]
            )
            if source_count >= self.source_limit or global_count >= self.global_limit:
                raise BootstrapRateLimitError(
                    "browser sense pairing rate limit exceeded"
                )
            conn.execute(
                """INSERT INTO browser_pairing_requests(
                    bootstrap_id,client_proof_hash,verifier_hash,public_key_jwk_json,public_key_hash,
                    device_label,client_mode,capabilities_json,source_hash,source_hint,confirmation_code,
                    exchange_challenge,created_at,expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bootstrap_id,
                    self._digest(client_proof),
                    normalized_verifier_hash,
                    public_jwk_json,
                    public_key_hash,
                    label,
                    mode,
                    json.dumps(normalized_capabilities),
                    source_hash,
                    self._source_hint(source),
                    confirmation_code,
                    challenge,
                    created_at,
                    expires_at,
                ),
            )
            self._append_pairing_event(
                conn, bootstrap_id, "pending", "device", None, created_at, {}
            )
        request = self._request_public(self._request_row(bootstrap_id), state="pending")
        self._emit(
            EventType.BROWSER_SENSE_BOOTSTRAP_REQUESTED,
            {
                "bootstrap_id": bootstrap_id,
                "device_label": label,
                "client_mode": mode,
                "capabilities": list(normalized_capabilities),
                "source_hint": request["source_hint"],
                "expires_at": expires_at,
            },
        )
        return {
            "bootstrap_id": bootstrap_id,
            "state": "pending",
            "confirmation_code": confirmation_code,
            "client_proof": client_proof,
            "exchange_challenge": challenge,
            "expires_at": expires_at,
            "request": request,
        }

    def _append_pairing_event(
        self,
        conn: sqlite3.Connection,
        bootstrap_id: str,
        state: str,
        actor: str,
        reason: str | None,
        recorded_at: str,
        payload: Mapping[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO browser_pairing_events VALUES(?,?,?,?,?,?,?)",
            (
                new_id("sense-bootstrap-event"),
                bootstrap_id,
                state,
                actor,
                reason,
                recorded_at,
                _canonical(payload),
            ),
        )

    def _request_row(self, bootstrap_id: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_pairing_requests WHERE bootstrap_id=?",
                (bootstrap_id,),
            ).fetchone()
        if row is None:
            raise KeyError(bootstrap_id)
        return row

    def _request_state(self, bootstrap_id: str, *, expire: bool = True) -> str:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM browser_pairing_requests WHERE bootstrap_id=?",
                (bootstrap_id,),
            ).fetchone()
            if row is None:
                raise KeyError(bootstrap_id)
            latest = self._latest_pairing_event(conn, bootstrap_id)
            state = str(latest["state"])
            if (
                expire
                and state in {"pending", "approved"}
                and self._now() >= _parse(row["expires_at"])
            ):
                recorded_at = _iso(self._now())
                self._append_pairing_event(
                    conn,
                    bootstrap_id,
                    "expired",
                    "gateway",
                    "pairing-timeout",
                    recorded_at,
                    {},
                )
                state = "expired"
                self._emit(
                    EventType.BROWSER_SENSE_BOOTSTRAP_EXPIRED,
                    {"bootstrap_id": bootstrap_id},
                    severity="warning",
                )
            return state

    @staticmethod
    def _request_public(row: sqlite3.Row, *, state: str) -> dict[str, Any]:
        return {
            "bootstrap_id": row["bootstrap_id"],
            "state": state,
            "confirmation_code": row["confirmation_code"],
            "device_label": row["device_label"],
            "client_mode": row["client_mode"],
            "capabilities": json.loads(row["capabilities_json"]),
            "source_hint": row["source_hint"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def _authenticate_client_proof(self, row: sqlite3.Row, client_proof: str) -> None:
        if not client_proof or not hmac.compare_digest(
            row["client_proof_hash"], self._digest(client_proof)
        ):
            raise PermissionError("invalid bootstrap client proof")

    def status(self, bootstrap_id: str, *, client_proof: str) -> dict[str, Any]:
        row = self._request_row(bootstrap_id)
        self._authenticate_client_proof(row, client_proof)
        state = self._request_state(bootstrap_id)
        payload = self._request_public(row, state=state)
        if state in {"pending", "approved"}:
            payload["exchange_challenge"] = row["exchange_challenge"]
        return payload

    def list_requests(
        self, *, state: str = "pending", limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browser_pairing_requests ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            current = self._request_state(row["bootstrap_id"])
            if state != "all" and current != state:
                continue
            result.append(self._request_public(row, state=current))
        return result

    def decide(
        self,
        bootstrap_id: str,
        *,
        approved: bool,
        principal: str,
        reason: str,
        channel: str,
    ) -> dict[str, Any]:
        row = self._request_row(bootstrap_id)
        state = self._request_state(bootstrap_id)
        target = "approved" if approved else "denied"
        if state == target:
            return {**self._request_public(row, state=state), "replayed": True}
        if state != "pending":
            raise BootstrapStateError(f"pairing request is {state}")
        recorded_at = _iso(self._now())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = self._latest_pairing_event(conn, bootstrap_id)
            if latest is None or latest["state"] != "pending":
                raise BootstrapStateError("pairing request decision conflict")
            self._append_pairing_event(
                conn,
                bootstrap_id,
                target,
                principal,
                reason.strip() or "explicit-decision",
                recorded_at,
                {"channel": channel},
            )
        self._emit(
            EventType.BROWSER_SENSE_BOOTSTRAP_APPROVED
            if approved
            else EventType.BROWSER_SENSE_BOOTSTRAP_DENIED,
            {
                "bootstrap_id": bootstrap_id,
                "principal": principal,
                "channel": channel,
                "confirmation_code": row["confirmation_code"],
            },
        )
        return {**self._request_public(row, state=target), "replayed": False}

    def exchange(
        self,
        bootstrap_id: str,
        *,
        client_proof: str,
        verifier: str,
        device_signature: str,
        principal: str = "founder",
    ) -> dict[str, Any]:
        row = self._request_row(bootstrap_id)
        self._authenticate_client_proof(row, client_proof)
        state = self._request_state(bootstrap_id)
        if self._now() >= _parse(row["expires_at"]):
            raise BootstrapStateError("pairing exchange replay window expired")
        if state != "approved":
            raise BootstrapStateError(f"pairing request is {state}")
        try:
            verifier_bytes = _unb64url(verifier)
        except ValueError as exc:
            raise PermissionError("invalid pairing verifier") from exc
        if len(verifier_bytes) != 32 or not hmac.compare_digest(
            row["verifier_hash"], hashlib.sha256(verifier_bytes).hexdigest()
        ):
            raise PermissionError("invalid pairing verifier")
        self._verify_signature(
            json.loads(row["public_key_jwk_json"]),
            row["exchange_challenge"],
            device_signature,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE bootstrap_id=?",
                (bootstrap_id,),
            ).fetchone()
            if existing is not None:
                raise BootstrapStateError("pairing exchange was already consumed")
            device_id = new_id("sense-device")
            credential = _b64url(secrets.token_bytes(32))
            created_at = _iso(self._now())
            expires_at = _iso(
                self._now() + timedelta(seconds=self.device_absolute_seconds)
            )
            conn.execute(
                "INSERT INTO browser_paired_devices VALUES(?,?,?,?,?,?,?)",
                (
                    device_id,
                    bootstrap_id,
                    principal,
                    row["public_key_jwk_json"],
                    self._digest(credential),
                    created_at,
                    expires_at,
                ),
            )
            conn.execute(
                "INSERT INTO browser_device_events VALUES(?,?,?,?,?,?,?)",
                (
                    new_id("sense-device-event"),
                    device_id,
                    "active",
                    principal,
                    "pairing-exchange",
                    created_at,
                    "{}",
                ),
            )
            self._append_pairing_event(
                conn,
                bootstrap_id,
                "exchanged",
                principal,
                "one-time-exchange",
                created_at,
                {"device_id": device_id},
            )
            existing = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
        device = self._device_public(
            existing, state=self._device_state(device_id, touch=False)
        )
        self._emit(
            EventType.BROWSER_SENSE_BOOTSTRAP_EXCHANGED,
            {
                "bootstrap_id": bootstrap_id,
                "device_id": device_id,
                "replayed": False,
            },
        )
        return {"device": device, "credential": credential, "replayed": False}

    @staticmethod
    def _device_public(row: sqlite3.Row, *, state: str) -> dict[str, Any]:
        return {
            "device_id": row["device_id"],
            "principal": row["principal"],
            "state": state,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    def _device_state(self, device_id: str, *, touch: bool) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE device_id=?", (device_id,)
            ).fetchone()
            if row is None:
                raise DeviceCredentialError("unknown paired device")
            latest = self._latest_device_event(conn, device_id)
            state = str(latest["state"])
            last_seen = _parse(latest["recorded_at"])
            now = self._now()
            if state == "active" and (
                now >= _parse(row["expires_at"])
                or now - last_seen > timedelta(seconds=self.device_idle_seconds)
            ):
                state = "expired"
                conn.execute(
                    "INSERT INTO browser_device_events VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id("sense-device-event"),
                        device_id,
                        state,
                        "gateway",
                        "credential-expired",
                        _iso(now),
                        "{}",
                    ),
                )
            elif state == "active" and touch:
                conn.execute(
                    "INSERT INTO browser_device_events VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id("sense-device-event"),
                        device_id,
                        state,
                        "device",
                        "credential-used",
                        _iso(now),
                        "{}",
                    ),
                )
            return state

    def authenticate_device(
        self, credential: str, *, touch: bool = True
    ) -> dict[str, Any]:
        if not credential:
            raise DeviceCredentialError("missing paired device credential")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE credential_hash=?",
                (self._digest(credential),),
            ).fetchone()
        if row is None or self._device_state(row["device_id"], touch=touch) != "active":
            raise DeviceCredentialError(
                "paired device credential is invalid, expired, or revoked"
            )
        return self._device_public(row, state="active")

    def create_session_challenge(self, credential: str) -> dict[str, Any]:
        device = self.authenticate_device(credential)
        challenge_id = new_id("sense-challenge")
        nonce = _b64url(secrets.token_bytes(32))
        challenge = "\n".join(
            (
                "aether.senses.session.v1",
                f"challenge_id={challenge_id}",
                f"device_id={device['device_id']}",
                f"origin={self.allowed_origin}",
                f"nonce={nonce}",
            )
        )
        created_at = _iso(self._now())
        expires_at = _iso(self._now() + timedelta(seconds=self.challenge_ttl_seconds))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_session_challenges VALUES(?,?,?,?,?)",
                (challenge_id, device["device_id"], challenge, created_at, expires_at),
            )
            conn.execute(
                "INSERT INTO browser_session_challenge_events VALUES(?,?,?,?)",
                (new_id("sense-challenge-event"), challenge_id, "issued", created_at),
            )
        return {
            "challenge_id": challenge_id,
            "challenge": challenge,
            "expires_at": expires_at,
        }

    def consume_session_challenge(
        self,
        credential: str,
        *,
        challenge_id: str,
        device_signature: str,
    ) -> dict[str, Any]:
        device = self.authenticate_device(credential)
        with self._connect() as conn:
            challenge = conn.execute(
                "SELECT * FROM browser_session_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if challenge is None or challenge["device_id"] != device["device_id"]:
                raise DeviceCredentialError("invalid device session challenge")
            latest = self._latest_challenge_event(conn, challenge_id)
            if (
                latest is None
                or latest["state"] != "issued"
                or self._now() >= _parse(challenge["expires_at"])
            ):
                raise DeviceCredentialError(
                    "device session challenge expired or was already used"
                )
            device_row = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE device_id=?",
                (device["device_id"],),
            ).fetchone()
        self._verify_signature(
            json.loads(device_row["public_key_jwk_json"]),
            challenge["challenge"],
            device_signature,
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            latest = self._latest_challenge_event(conn, challenge_id)
            if (
                latest is None
                or latest["state"] != "issued"
                or self._now() >= _parse(challenge["expires_at"])
            ):
                raise DeviceCredentialError(
                    "device session challenge expired or was already used"
                )
            conn.execute(
                "INSERT INTO browser_session_challenge_events VALUES(?,?,?,?)",
                (
                    new_id("sense-challenge-event"),
                    challenge_id,
                    "used",
                    _iso(self._now()),
                ),
            )
        return device

    def bind_session(
        self,
        *,
        session_id: str,
        device_id: str,
        session_credential: str,
        expires_at: str,
    ) -> str:
        csrf_nonce = _b64url(secrets.token_bytes(32))
        created_at = _iso(self._now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_session_bindings VALUES(?,?,?,?,?,?)",
                (
                    session_id,
                    device_id,
                    self._digest(session_credential),
                    self._digest(csrf_nonce),
                    created_at,
                    expires_at,
                ),
            )
            self._append_session_event(
                conn, session_id, "issued", created_at, {"last_seen_at": created_at}
            )
        self._emit(
            EventType.BROWSER_SENSE_SESSION_CREDENTIAL_ISSUED,
            {
                "session_id": session_id,
                "device_id": device_id,
                "expires_at": expires_at,
            },
        )
        return csrf_nonce

    @staticmethod
    def _append_session_event(
        conn: sqlite3.Connection,
        session_id: str,
        state: str,
        recorded_at: str,
        payload: Mapping[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO browser_session_binding_events VALUES(?,?,?,?,?)",
            (
                new_id("sense-session-auth-event"),
                session_id,
                state,
                recorded_at,
                _canonical(payload),
            ),
        )

    def authenticate_session(
        self,
        credential: str,
        *,
        csrf_nonce: str | None,
        require_csrf: bool = True,
    ) -> dict[str, Any]:
        if not credential:
            raise SessionCredentialError("missing browser sense session credential")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_session_bindings WHERE credential_hash=?",
                (self._digest(credential),),
            ).fetchone()
            if row is None:
                raise SessionCredentialError("invalid browser sense session credential")
            latest = self._latest_session_event(conn, row["session_id"])
            state = str(latest["state"])
            payload = json.loads(latest["payload_json"])
            last_seen = _parse(
                str(payload.get("last_seen_at") or latest["recorded_at"])
            )
        if self._device_state(row["device_id"], touch=True) != "active":
            raise SessionCredentialError("paired device is expired or revoked")
        if state in {"closed", "expired"}:
            raise SessionCredentialError(f"browser sense session credential is {state}")
        now = self._now()
        if now >= _parse(row["expires_at"]) or (
            state != "active"
            and now - last_seen > timedelta(seconds=self.session_idle_seconds)
        ):
            self.close_session(
                row["session_id"], reason="session-credential-expired", state="expired"
            )
            raise SessionCredentialError("browser sense session credential expired")
        if require_csrf and (
            not csrf_nonce
            or not hmac.compare_digest(row["csrf_hash"], self._digest(csrf_nonce))
        ):
            raise SessionCredentialError("invalid browser sense CSRF nonce")
        recorded_at = _iso(now)
        with self._connect() as conn:
            self._append_session_event(
                conn,
                row["session_id"],
                state,
                recorded_at,
                {"last_seen_at": recorded_at},
            )
        return {
            "session_id": row["session_id"],
            "device_id": row["device_id"],
            "state": state,
        }

    def mark_session_state(self, session_id: str, state: str) -> None:
        if state not in {"issued", "active", "closed", "expired"}:
            raise ValueError("unsupported browser sense session credential state")
        recorded_at = _iso(self._now())
        with self._connect() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM browser_session_bindings WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                is None
            ):
                raise KeyError(session_id)
            self._append_session_event(
                conn, session_id, state, recorded_at, {"last_seen_at": recorded_at}
            )

    def close_session(
        self, session_id: str, *, reason: str, state: str = "closed"
    ) -> bool:
        recorded_at = _iso(self._now())
        with self._connect() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM browser_session_bindings WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                is None
            ):
                return False
            latest = self._latest_session_event(conn, session_id)
            if latest["state"] in {"closed", "expired"}:
                return False
            self._append_session_event(
                conn,
                session_id,
                state,
                recorded_at,
                {"last_seen_at": recorded_at, "reason": reason},
            )
        return True

    def revoke_device(
        self, device_id: str, *, principal: str, reason: str
    ) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM browser_paired_devices WHERE device_id=?", (device_id,)
            ).fetchone()
            if row is None:
                raise KeyError(device_id)
            latest = self._latest_device_event(conn, device_id)
            replayed = latest["state"] == "revoked"
            recorded_at = _iso(self._now())
            if not replayed:
                conn.execute(
                    "INSERT INTO browser_device_events VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id("sense-device-event"),
                        device_id,
                        "revoked",
                        principal,
                        reason,
                        recorded_at,
                        "{}",
                    ),
                )
            session_rows = conn.execute(
                "SELECT session_id FROM browser_session_bindings WHERE device_id=?",
                (device_id,),
            ).fetchall()
        closed: list[str] = []
        for session_row in session_rows:
            if self.close_session(session_row["session_id"], reason="device-revoked"):
                closed.append(session_row["session_id"])
        self._emit(
            EventType.BROWSER_SENSE_DEVICE_REVOKED,
            {
                "device_id": device_id,
                "principal": principal,
                "sessions_closed": closed,
                "replayed": replayed,
            },
            severity="warning",
        )
        return {
            "device_id": device_id,
            "state": "revoked",
            "sessions_closed": closed,
            "replayed": replayed,
        }

    def status_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            return {
                "policy_id": "aether.browser-senses.bootstrap.v1",
                "allowed_origin": self.allowed_origin,
                "pairing_ttl_seconds": self.pairing_ttl_seconds,
                "device_absolute_seconds": self.device_absolute_seconds,
                "device_idle_seconds": self.device_idle_seconds,
                "session_absolute_seconds": self.session_absolute_seconds,
                "session_idle_seconds": self.session_idle_seconds,
                "pairing_requests": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM browser_pairing_requests"
                    ).fetchone()[0]
                ),
                "paired_devices": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM browser_paired_devices"
                    ).fetchone()[0]
                ),
                "session_bindings": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM browser_session_bindings"
                    ).fetchone()[0]
                ),
                "secrets_exposed": False,
            }
