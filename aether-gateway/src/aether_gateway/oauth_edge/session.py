"""Founder browser session for the OAuth Edge consent flow.

P0-remaining (ChatGPT review, PR #60): a plain HTML consent form cannot carry
the secret ``X-Aether-Operator-Token`` header — browsers only send it when a
form is authored with an explicit header, and this edge's consent page is a
static ``<form method="POST">``. Founder browser approval therefore uses a
short-lived, HttpOnly, signed session cookie established by a one-time login
(``POST /oauth/login``) and accepted ONLY for the consent decision endpoints
(``POST /oauth/approve``, ``POST /oauth/reject``).

The cookie value is an HMAC-SHA256 signed payload (same mechanism and secret
family as the edge access tokens) carrying an explicit ``purpose`` claim so a
founding-session cookie can never be mistaken for an MCP access token, a
``sub`` (the authenticated Founder principal), and an ``exp`` deadline.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Optional

from .token_store import _hmac_sign, _hmac_verify

SESSION_COOKIE_NAME = "aether_oauth_founder"
SESSION_TTL = int(os.getenv("AETHER_OAUTH_SESSION_TTL", "1800"))
SESSION_SECURE = os.getenv("AETHER_OAUTH_SESSION_SECURE", "1") == "1"


def _secret() -> bytes:
    raw = os.getenv("AETHER_OAUTH_EDGE_SECRET", "")
    if not raw or len(raw) < 32:
        raise ValueError(
            "AETHER_OAUTH_EDGE_SECRET must be set and at least 32 characters for founding-session cookies."
        )
    return raw.encode()


def sign_founder_session(principal: str) -> str:
    """Create a signed founding-session cookie value for ``principal``."""
    now = int(time.time())
    payload = {
        "purpose": "founder-session",
        "sub": principal,
        "iat": now,
        "exp": now + SESSION_TTL,
        "jti": str(uuid.uuid4()),
    }
    return _hmac_sign(payload, _secret())


def verify_founder_session(token: str) -> Optional[str]:
    """Return the Founder principal iff ``token`` is a valid, unexpired session."""
    payload = _hmac_verify(token, _secret())
    if payload is None:
        return None
    if payload.get("purpose") != "founder-session":
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload.get("sub")