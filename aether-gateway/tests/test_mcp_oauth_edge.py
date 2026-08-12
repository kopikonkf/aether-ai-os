"""Tests for Aether MCP OAuth Edge — ADR-0056."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Patch env before importing server
import os
os.environ["AETHER_OAUTH_EDGE_SECRET"] = "test-secret-key-minimum-32-bytes-ok!"
os.environ["AETHER_MCP_TOKEN"] = "test-mcp-token-for-unit-tests"
# tests/ is at aether-gateway/tests/ — repo root is 3 levels up
os.environ["AETHER_PRINCIPAL_REGISTRY"] = str(
    Path(__file__).parent.parent.parent / "configs" / "principal_registry.yaml"
)

import aether_gateway.oauth_edge.registry as _reg_module
_reg_module._registry = None  # reset singleton before first import resolves it

from aether_gateway.oauth_edge.server import app
from aether_gateway.oauth_edge.token_store import TokenStore, _hmac_sign, _hmac_verify
from aether_gateway.oauth_edge.registry import PrincipalRegistry, get_registry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def store(tmp_path):
    """Isolated TokenStore backed by a temp SQLite DB."""
    secret = b"test-secret-key-minimum-32-bytes-ok!"
    return TokenStore(db_path=tmp_path / "tokens.db", secret=secret)


# ---------------------------------------------------------------------------
# Token signing / verification
# ---------------------------------------------------------------------------

class TestHmacToken:
    def test_sign_and_verify(self):
        secret = b"test-secret-key-minimum-32-bytes-ok!"
        payload = {"sub": "chatgpt", "principal_id": "chatgpt", "exp": int(time.time()) + 3600}
        token = _hmac_sign(payload, secret)
        result = _hmac_verify(token, secret)
        assert result is not None
        assert result["principal_id"] == "chatgpt"

    def test_tampered_token_rejected(self):
        secret = b"test-secret-key-minimum-32-bytes-ok!"
        payload = {"sub": "chatgpt", "exp": int(time.time()) + 3600}
        token = _hmac_sign(payload, secret)
        # Tamper with middle part
        parts = token.split(".")
        parts[1] = parts[1][:-2] + "XX"
        bad_token = ".".join(parts)
        assert _hmac_verify(bad_token, secret) is None

    def test_wrong_secret_rejected(self):
        secret = b"test-secret-key-minimum-32-bytes-ok!"
        other_secret = b"other-secret-key-minimum-32-bytes-ok"
        payload = {"sub": "chatgpt", "exp": int(time.time()) + 3600}
        token = _hmac_sign(payload, secret)
        assert _hmac_verify(token, other_secret) is None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_known_principal_by_client_id(self):
        registry = get_registry()
        p = registry.get_by_client_id("aether-principal-chatgpt")
        assert p is not None
        assert p.id == "chatgpt"
        assert "aether.read" in p.allowed_scopes

    def test_unknown_client_id_returns_none(self):
        registry = get_registry()
        assert registry.get_by_client_id("unknown-client") is None

    def test_mutation_authority_chatgpt_false(self):
        registry = get_registry()
        p = registry.get_by_client_id("aether-principal-chatgpt")
        assert p.mutation_authority is False

    def test_mutation_authority_codex_true(self):
        registry = get_registry()
        p = registry.get_by_client_id("aether-principal-codex")
        assert p.mutation_authority is True

    def test_effective_scopes_drops_mutate_when_no_authority(self):
        registry = get_registry()
        p = registry.get_by_client_id("aether-principal-chatgpt")
        scopes = p.effective_scopes(["aether.read", "aether.diagnostic", "aether.mutate"])
        assert "aether.mutate" not in scopes
        assert "aether.read" in scopes

    def test_effective_scopes_allows_mutate_for_codex(self):
        registry = get_registry()
        p = registry.get_by_client_id("aether-principal-codex")
        scopes = p.effective_scopes(["aether.read", "aether.mutate"])
        assert "aether.mutate" in scopes


# ---------------------------------------------------------------------------
# TokenStore
# ---------------------------------------------------------------------------

class TestTokenStore:
    def test_issue_and_verify_access_token(self, store):
        token, ttl = store.issue_access_token("chatgpt", ["aether.read"])
        payload = store.verify_access_token(token)
        assert payload is not None
        assert payload["principal_id"] == "chatgpt"
        assert payload["scopes"] == ["aether.read"]

    def test_expired_token_rejected(self, store):
        # Issue a token with past expiry
        now = int(time.time())
        payload = {"sub": "chatgpt", "principal_id": "chatgpt", "scopes": [], "exp": now - 1, "iat": now, "jti": "x"}
        token = _hmac_sign(payload, store._secret)
        assert store.verify_access_token(token) is None

    def test_refresh_token_rotation(self, store):
        refresh = store.issue_refresh_token("chatgpt", ["aether.read"])
        result = store.consume_refresh_token(refresh)
        assert result is not None
        principal_id, scopes = result
        assert principal_id == "chatgpt"
        # Token is now consumed — cannot use again
        assert store.consume_refresh_token(refresh) is None

    def test_refresh_token_strips_mutate(self, store):
        # mutate scope must never auto-renew via refresh
        refresh = store.issue_refresh_token("codex", ["aether.read", "aether.mutate"])
        result = store.consume_refresh_token(refresh)
        assert result is not None
        _, scopes = result
        assert "aether.mutate" not in scopes

    def test_pending_auth_lifecycle(self, store):
        req = store.create_pending_auth(
            principal_id="chatgpt",
            client_id="aether-principal-chatgpt",
            redirect_uri="https://chatgpt.com/callback",
            scopes=["aether.read"],
            code_challenge="abc123",
            code_challenge_method="S256",
            state="state123",
        )
        assert store.get_pending_auth(req.request_id) is not None

        code = store.approve_auth(req.request_id)
        assert code is not None

        pending = store.consume_auth_code(code)
        assert pending is not None
        assert pending.principal_id == "chatgpt"

        # Code is single-use
        assert store.consume_auth_code(code) is None

    def test_reject_auth(self, store):
        req = store.create_pending_auth(
            principal_id="chatgpt",
            client_id="aether-principal-chatgpt",
            redirect_uri="https://chatgpt.com/callback",
            scopes=["aether.read"],
            code_challenge="abc",
            code_challenge_method="S256",
            state="s",
        )
        store.reject_auth(req.request_id)
        pending = store.get_pending_auth(req.request_id)
        assert pending is not None
        assert pending.approved is False


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovery_endpoint(self, client):
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "aether.read" in data["scopes_supported"]
        assert "S256" in data["code_challenge_methods_supported"]


class TestRegistration:
    def test_known_client_registered(self, client):
        resp = client.post("/oauth/register", json={"client_id": "aether-principal-chatgpt"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"] == "aether-principal-chatgpt"

    def test_unknown_client_rejected(self, client):
        resp = client.post("/oauth/register", json={"client_id": "rogue-client"})
        assert resp.status_code == 400
        data = resp.json()
        assert data["detail"]["error"] == "invalid_client_metadata"


class TestAuthorize:
    def test_authorize_renders_approval_page(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read aether.diagnostic",
            "state": "abc123",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        })
        assert resp.status_code == 200
        assert "ChatGPT" in resp.text
        assert "aether.read" in resp.text

    def test_unknown_client_returns_error(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "rogue-client",
            "redirect_uri": "https://evil.com/callback",
            "scope": "aether.read",
            "state": "s",
            "code_challenge": "abc",
        })
        assert resp.status_code == 400

    def test_missing_pkce_returns_error(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read",
            "state": "s",
            # no code_challenge
        })
        assert resp.status_code == 400


class TestApproveReject:
    def _create_pending(self, client):
        """Helper: trigger authorize to create a pending request, return request_id."""
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read",
            "state": "state123",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        })
        assert resp.status_code == 200
        # Extract request_id from HTML
        text = resp.text
        start = text.find("Request ID: ") + len("Request ID: ")
        end = text.find("<", start)
        return text[start:end].strip()

    def test_approve_redirects_with_code(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "code=" in location
        assert "state=state123" in location

    def test_reject_redirects_with_error(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/reject/{request_id}", follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "error=access_denied" in location

    def test_invalid_request_id_returns_400(self, client):
        resp = client.post("/oauth/approve/nonexistent-id")
        assert resp.status_code == 400


class TestTokenEndpoint:
    def _get_auth_code(self, client):
        """Full flow: authorize → approve → return code."""
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read aether.diagnostic",
            "state": "s",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        })
        text = resp.text
        start = text.find("Request ID: ") + len("Request ID: ")
        end = text.find("<", start)
        request_id = text[start:end].strip()

        approve_resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False)
        location = approve_resp.headers["location"]
        code = location.split("code=")[1].split("&")[0]
        return code

    def test_code_exchange_returns_tokens(self, client):
        code = self._get_auth_code(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0

    def test_invalid_code_returns_400(self, client):
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": "bad-code",
            "client_id": "aether-principal-chatgpt",
        })
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    def test_unsupported_grant_type(self, client):
        resp = client.post("/oauth/token", data={"grant_type": "client_credentials"})
        assert resp.status_code == 400
        assert resp.json()["error"] == "unsupported_grant_type"


class TestMCPProxy:
    def test_no_token_returns_401(self, client):
        resp = client.post("/mcp", json={})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.post("/mcp", json={}, headers={"Authorization": "Bearer bad-token"})
        assert resp.status_code == 401

    def test_valid_token_proxied(self, client):
        """Valid token should trigger upstream proxy call."""
        secret = b"test-secret-key-minimum-32-bytes-ok!"
        store = TokenStore(db_path=Path("/tmp/test-proxy-tokens.db"), secret=secret)
        token, _ = store.issue_access_token("chatgpt", ["aether.read"])

        mock_response = MagicMock()
        mock_response.content = b'{"result": "ok"}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        with patch("aether_gateway.oauth_edge.server.get_store", return_value=store):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client

                resp = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200


class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "aether-mcp-oauth-edge"
