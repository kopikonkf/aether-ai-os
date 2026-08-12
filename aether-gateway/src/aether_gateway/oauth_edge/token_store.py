"""Token store for Aether MCP OAuth Edge.

Manages:
- Authorization codes (short-lived, in-memory, single-use)
- Access tokens (JWT, signed with AETHER_OAUTH_EDGE_SECRET)
- Refresh tokens (hashed SHA-256, stored in SQLite under AETHER_HOME)
- Pending authorization requests (waiting for Founder approval)

ADR-0056 security constraints:
- AETHER_MCP_TOKEN is never stored here or returned to callers
- Refresh token plaintext returned only once at issuance
- aether.mutate scope never auto-renewed via refresh
- Audit trail written to append-only JSONL
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# PyJWT is a lightweight dep already available via cryptography chain.
# We use HMAC-SHA256 manually to avoid adding jwt as a hard dep right now.


def _hmac_sign(payload: dict, secret: bytes) -> str:
    """Minimal JWT-like signed token (HS256). Not a full JWT library."""
    import base64

    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    body_bytes = json.dumps(payload, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(body_bytes).rstrip(b"=").decode()
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{header}.{body}.{sig_b64}"


def _hmac_verify(token: str, secret: bytes) -> Optional[dict]:
    """Verify and decode a token produced by _hmac_sign. Returns payload or None."""
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, body, sig = parts
        signing_input = f"{header}.{body}".encode()
        expected_sig = hmac.new(secret, signing_input, hashlib.sha256).digest()
        expected_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()
        if not hmac.compare_digest(sig, expected_b64):
            return None
        padding = 4 - len(body) % 4
        body_bytes = base64.urlsafe_b64decode(body + "=" * (padding % 4))
        return json.loads(body_bytes)
    except Exception:
        return None


ACCESS_TOKEN_TTL = int(os.getenv("AETHER_OAUTH_ACCESS_TTL", "3600"))   # 1 hour
REFRESH_TOKEN_TTL = int(os.getenv("AETHER_OAUTH_REFRESH_TTL", "2592000"))  # 30 days
AUTH_CODE_TTL = 300  # 5 minutes


@dataclass
class PendingAuth:
    """An authorization request waiting for Founder approval."""
    request_id: str
    principal_id: str
    client_id: str
    redirect_uri: str
    scopes: list[str]
    code_challenge: str
    code_challenge_method: str
    state: str
    created_at: float = field(default_factory=time.time)
    approved: Optional[bool] = None  # None=pending, True=approved, False=rejected
    auth_code: Optional[str] = None  # set when approved
    approval_id: Optional[str] = None  # governed Trusted Approval Inbox link
    approving_principal: Optional[str] = None  # authenticated Founder who decided


class TokenStore:
    """Manages tokens for the OAuth edge. Thread-safe via SQLite WAL."""

    def __init__(self, db_path: Optional[Path] = None, secret: Optional[bytes] = None) -> None:
        if db_path is None:
            aether_home = os.getenv("AETHER_HOME", r"C:\ProgramData\Aether")
            db_path = Path(aether_home) / "runtime" / "oauth-edge" / "tokens.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path

        if secret is None:
            raw = os.getenv("AETHER_OAUTH_EDGE_SECRET", "")
            if not raw or len(raw) < 32:
                raise ValueError(
                    "AETHER_OAUTH_EDGE_SECRET must be set and at least 32 characters. "
                    "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            secret = raw.encode()
        self._secret = secret

        # In-memory pending auth requests (cleared on restart — that's fine,
        # pending requests older than AUTH_CODE_TTL are invalid anyway)
        self._pending: dict[str, PendingAuth] = {}

        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    jti TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    client_id TEXT NOT NULL DEFAULT '',
                    scopes TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    issued_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rt_hash ON refresh_tokens(token_hash)
            """)
            # Migration (P1 #7): existing databases created before client_id binding
            # lack the column — add it if missing rather than failing on INSERT.
            cols = [r[1] for r in conn.execute("PRAGMA table_info(refresh_tokens)").fetchall()]
            if "client_id" not in cols:
                conn.execute("ALTER TABLE refresh_tokens ADD COLUMN client_id TEXT NOT NULL DEFAULT ''")

    # ------------------------------------------------------------------ #
    # Pending authorization requests                                       #
    # ------------------------------------------------------------------ #

    def create_pending_auth(
        self,
        principal_id: str,
        client_id: str,
        redirect_uri: str,
        scopes: list[str],
        code_challenge: str,
        code_challenge_method: str,
        state: str,
    ) -> PendingAuth:
        req = PendingAuth(
            request_id=str(uuid.uuid4()),
            principal_id=principal_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=scopes,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
        )
        self._pending[req.request_id] = req
        return req

    def get_pending_auth(self, request_id: str) -> Optional[PendingAuth]:
        req = self._pending.get(request_id)
        if req is None:
            return None
        if time.time() - req.created_at > AUTH_CODE_TTL:
            self._pending.pop(request_id, None)
            return None
        return req

    def approve_auth(self, request_id: str) -> Optional[str]:
        """Founder approves — generate and return auth code."""
        req = self.get_pending_auth(request_id)
        if req is None or req.approved is not None:
            return None
        code = secrets.token_urlsafe(32)
        req.approved = True
        req.auth_code = code
        return code

    def reject_auth(self, request_id: str) -> bool:
        req = self.get_pending_auth(request_id)
        if req is None:
            return False
        req.approved = False
        return True

    def cancel_pending_auth(self, request_id: str) -> None:
        """Drop a pending authorization request without deciding it.

        Used for fail-closed rollback when the governed Trusted Approval
        submission fails: an authorization that could not be mirrored into the
        governance inbox must never linger as an approvable request.
        """
        self._pending.pop(request_id, None)

    def consume_auth_code(self, code: str) -> Optional[PendingAuth]:
        """Single-use: consume auth code and return the associated request."""
        for req_id, req in list(self._pending.items()):
            if req.auth_code == code and req.approved is True:
                del self._pending[req_id]
                return req
        return None

    def get_pending_auth_by_code(self, code: str) -> Optional[PendingAuth]:
        """Non-destructive lookup by authorization code (P0 #4).

        Validates PKCE/client binding BEFORE the code is consumed, so a failed
        PKCE check does not invalidate the code. Atomic single-use semantics
        are preserved by consume_auth_code() remaining the only destructive path.
        """
        for req in self._pending.values():
            if req.auth_code == code and req.approved is True:
                if time.time() - req.created_at <= AUTH_CODE_TTL:
                    return req
        return None

    def list_pending_auths(self) -> list[PendingAuth]:
        now = time.time()
        result = []
        for req in list(self._pending.values()):
            if now - req.created_at <= AUTH_CODE_TTL and req.approved is None:
                result.append(req)
        return result

    # ------------------------------------------------------------------ #
    # Access tokens                                                         #
    # ------------------------------------------------------------------ #

    def issue_access_token(self, principal_id: str, scopes: list[str]) -> tuple[str, int]:
        """Issue a signed access token. Returns (token, expires_in_seconds)."""
        now = int(time.time())
        payload = {
            "sub": principal_id,
            "principal_id": principal_id,
            "scopes": scopes,
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
            "jti": str(uuid.uuid4()),
            "iss": os.getenv("AETHER_OAUTH_ISSUER", "https://aethers.my.id/oauth"),
            "aud": os.getenv("AETHER_OAUTH_AUDIENCE", "https://aethers.my.id/mcp"),
        }
        token = _hmac_sign(payload, self._secret)
        return token, ACCESS_TOKEN_TTL

    def verify_access_token(self, token: str) -> Optional[dict]:
        """Verify and return the decoded payload, or None if invalid/expired."""
        payload = _hmac_verify(token, self._secret)
        if payload is None:
            return None
        if payload.get("exp", 0) < time.time():
            return None
        # P1 #9: verify iss/aud claims
        expected_iss = os.getenv("AETHER_OAUTH_ISSUER", "https://aethers.my.id/oauth")
        expected_aud = os.getenv("AETHER_OAUTH_AUDIENCE", "https://aethers.my.id/mcp")
        if payload.get("iss") != expected_iss:
            return None
        if payload.get("aud") != expected_aud:
            return None
        return payload

    # ------------------------------------------------------------------ #
    # Refresh tokens                                                        #
    # ------------------------------------------------------------------ #

    def issue_refresh_token(self, principal_id: str, scopes: list[str], client_id: str = "") -> str:
        """Issue a refresh token. Plaintext returned only here; stored as SHA-256."""
        # aether.mutate is never auto-renewed via refresh
        safe_scopes = [s for s in scopes if s != "aether.mutate"]

        plaintext = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        jti = str(uuid.uuid4())
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO refresh_tokens (jti, principal_id, client_id, scopes, token_hash, issued_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (jti, principal_id, client_id, json.dumps(safe_scopes), token_hash, now, now + REFRESH_TOKEN_TTL),
            )
        return plaintext

    def consume_refresh_token(self, plaintext: str, client_id: str = "") -> Optional[tuple[str, list[str]]]:
        """Validate and rotate a refresh token. Returns (principal_id, scopes) or None.

        P1 #7: refresh tokens are bound to client_id — a token issued for one
        OAuth client cannot be used by another.
        """
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT jti, principal_id, client_id, scopes, expires_at, revoked
                FROM refresh_tokens WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                return None
            jti, principal_id, rt_client_id, scopes_json, expires_at, revoked = row
            if revoked or time.time() > expires_at:
                return None
            if client_id and rt_client_id and client_id != rt_client_id:
                return None
            # Revoke the consumed token (rotation)
            conn.execute("UPDATE refresh_tokens SET revoked = 1 WHERE jti = ?", (jti,))
        scopes = json.loads(scopes_json)
        return principal_id, scopes

    def revoke_all_for_principal(self, principal_id: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE principal_id = ? AND revoked = 0",
                (principal_id,),
            )
            return cur.rowcount
