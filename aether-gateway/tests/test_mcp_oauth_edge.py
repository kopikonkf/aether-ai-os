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
os.environ["AETHER_OPERATOR_TOKEN"] = "test-operator-token"
os.environ["AETHER_OPERATOR_ID"] = "founder"
# Browser session cookie tests run over http://testserver — clear the Secure flag.
os.environ["AETHER_OAUTH_SESSION_SECURE"] = "0"
# tests/ is at aether-gateway/tests/ — repo root is 3 levels up
os.environ["AETHER_PRINCIPAL_REGISTRY"] = str(
    Path(__file__).parent.parent.parent / "configs" / "principal_registry.yaml"
)

import aether_gateway.oauth_edge.registry as _reg_module
_reg_module._registry = None  # reset singleton before first import resolves it

from aether_gateway.oauth_edge.server import app
from aether_gateway.oauth_edge.token_store import TokenStore, _hmac_sign, _hmac_verify
from aether_gateway.oauth_edge.registry import PrincipalRegistry, get_registry
from aether_gateway.oauth_edge import approval_inbox, session as oauth_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    # Isolate the governed Trusted Approval Inbox per test.
    approval_inbox.reset()
    os.environ["AETHER_OAUTH_GOVERNANCE_DB"] = str(tmp_path / "governance.sqlite3")
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

    _FOUNDER = {"X-Aether-Operator-Token": "test-operator-token"}

    def test_approve_redirects_with_code(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "code=" in location
        assert "state=state123" in location

    def test_reject_redirects_with_error(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/reject/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "error=access_denied" in location

    def test_invalid_request_id_returns_400(self, client):
        resp = client.post("/oauth/approve/nonexistent-id", headers=self._FOUNDER)
        assert resp.status_code == 400


class TestApprovalSecurity:
    """P0 #1 regression: no unauthenticated Founder authorization."""

    _FOUNDER = {"X-Aether-Operator-Token": "test-operator-token"}
    _AUTHORIZE = {
        "response_type": "code",
        "client_id": "aether-principal-chatgpt",
        "redirect_uri": "https://chatgpt.com/callback",
        "scope": "aether.read",
        "state": "state123",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
    }

    def _create_pending(self, client):
        resp = client.get("/oauth/authorize", params=self._AUTHORIZE)
        assert resp.status_code == 200
        text = resp.text
        start = text.find("Request ID: ") + len("Request ID: ")
        end = text.find("<", start)
        return text[start:end].strip()

    def test_approve_without_token_returns_401(self, client):
        """An anonymous caller holding only request_id cannot mint a code."""
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False)
        assert resp.status_code == 401

        # The governed proposal must still be pending — nothing was decided.
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_approve_with_wrong_token_returns_401(self, client):
        """A forged/incorrect Founder credential is rejected."""
        request_id = self._create_pending(client)
        resp = client.post(
            f"/oauth/approve/{request_id}",
            follow_redirects=False,
            headers={"X-Aether-Operator-Token": "wrong-token"},
        )
        assert resp.status_code == 401
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_reject_without_token_returns_401(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/reject/{request_id}", follow_redirects=False)
        assert resp.status_code == 401
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_approve_with_operator_token_issues_code(self, client):
        """Authenticated Founder approval still yields the GitHub-OAuth redirect."""
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "code=" in location
        assert "state=state123" in location
        assert approval_inbox.get_approval_status(request_id) == "approved"

    def test_authorize_creates_governed_pending_action(self, client):
        """Every authorize surfaces as a governed ActionProposal in the inbox."""
        request_id = self._create_pending(client)
        approval_id = approval_inbox.find_approval_id_by_request(request_id)
        assert approval_id is not None
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_authenticated_decision_recorded_on_reject(self, client):
        request_id = self._create_pending(client)
        resp = client.post(f"/oauth/reject/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 302
        assert "error=access_denied" in resp.headers["location"]
        assert approval_inbox.get_approval_status(request_id) == "rejected"

    def test_failed_approval_does_not_consume_request(self, client):
        """401 must not burn the pending request — a later Founder decision works."""
        request_id = self._create_pending(client)
        denied = client.post(f"/oauth/approve/{request_id}", follow_redirects=False)
        assert denied.status_code == 401

        approved = client.post(f"/oauth/approve/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert approved.status_code == 302
        assert "code=" in approved.headers["location"]


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

        approve_resp = client.post(
            f"/oauth/approve/{request_id}",
            follow_redirects=False,
            headers={"X-Aether-Operator-Token": "test-operator-token"},
        )
        assert approve_resp.status_code == 302
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


# ---------------------------------------------------------------------------
# Regression tests — P0 #2 scope enforcement, P0 #3 redirect binding,
# P0 #4 PKCE-before-consume, P1 #5 S256 enforce, P1 #7 refresh client binding
# ---------------------------------------------------------------------------

def _issue_token(scopes, principal="chatgpt", secret=b"test-secret-key-minimum-32-bytes-ok!"):
    store = TokenStore(db_path=Path("/tmp/test-regression-tokens.db"), secret=secret)
    token, _ = store.issue_access_token(principal, scopes)
    return token


class TestScopeEnforcement:
    """P0 #2 — read/diagnostic principals must NOT reach mutation tools."""

    def test_read_token_blocked_from_mutate(self, client):
        token = _issue_token(["aether.read"])
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "workspace_edit", "arguments": {}}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "insufficient_scope"

    def test_diagnostic_token_blocked_from_mutate(self, client):
        token = _issue_token(["aether.diagnostic"])
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "decide_and_resume", "arguments": {}}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_read_token_allowed_read_tool(self):
        # Verify no enforcement against allowed tools before reaching upstream
        token = _issue_token(["aether.read"])
        # hashes are deterministic; the read tool file_read requires aether.read only
        from aether_gateway.oauth_edge.server import TOOL_SCOPE_MAP
        assert "file_read" in TOOL_SCOPE_MAP
        assert "aether.read" in TOOL_SCOPE_MAP["file_read"]

    def test_mutate_token_allowed_mutate(self, client):
        token = _issue_token(["aether.read", "aether.mutate"])
        mock_response = MagicMock()
        mock_response.content = b'{"result": "ok"}'
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        with patch("aether_gateway.oauth_edge.server.get_store") as mock_store_cls:
            store = TokenStore(db_path=Path("/tmp/test-regression-tokens2.db"), secret=b"test-secret-key-minimum-32-bytes-ok!")
            # use real store; patch only httpx
            mock_store_cls.return_value = store
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.request = AsyncMock(return_value=mock_response)
                mock_client_cls.return_value = mock_client
                resp = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "workspace_edit", "arguments": {}}},
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200


class TestRedirectBinding:
    """P0 #3 — authorization code bound to client_id + redirect_uri."""

    def _get_code(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read",
            "state": "s",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        })
        text = resp.text
        start = text.find("Request ID: ") + len("Request ID: ")
        end = text.find("<", start)
        request_id = text[start:end].strip()
        approve = client.post(
            f"/oauth/approve/{request_id}",
            follow_redirects=False,
            headers={"X-Aether-Operator-Token": "test-operator-token"},
        )
        assert approve.status_code == 302
        return approve.headers["location"].split("code=")[1].split("&")[0]

    def test_wrong_client_id_rejected(self, client):
        code = self._get_code(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-codex",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    def test_wrong_redirect_uri_rejected(self, client):
        code = self._get_code(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://evil.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"


class TestPKCEBeforeConsume:
    """P0 #4 — wrong PKCE must NOT consume the authorization code."""

    def _get_code(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read",
            "state": "s",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
        })
        text = resp.text
        start = text.find("Request ID: ") + len("Request ID: ")
        end = text.find("<", start)
        request_id = text[start:end].strip()
        approve = client.post(
            f"/oauth/approve/{request_id}",
            follow_redirects=False,
            headers={"X-Aether-Operator-Token": "test-operator-token"},
        )
        assert approve.status_code == 302
        return approve.headers["location"].split("code=")[1].split("&")[0]

    def test_wrong_pkce_does_not_consume_code(self, client):
        code = self._get_code(client)
        wrong = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "WRONG_VERIFIER_VALUE_12345",
        })
        assert wrong.status_code == 400
        assert wrong.json()["error"] == "invalid_grant"

        # Code must still be valid — retry with correct verifier succeeds
        ok = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert ok.status_code == 200
        assert "access_token" in ok.json()

    def test_valid_pkce_single_use(self, client):
        code = self._get_code(client)
        ok = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert ok.status_code == 200

        # Second attempt -> invalid_grant (replay rejected)
        replay = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"


class TestS256Enforcement:
    """P1 #5 — plain PKCE method rejected."""

    def test_plain_pkce_rejected(self, client):
        resp = client.get("/oauth/authorize", params={
            "response_type": "code",
            "client_id": "aether-principal-chatgpt",
            "redirect_uri": "https://chatgpt.com/callback",
            "scope": "aether.read",
            "state": "s",
            "code_challenge": "abc123",
            "code_challenge_method": "plain",
        })
        assert resp.status_code == 400
        assert "S256" in resp.text


class TestRefreshClientBinding:
    """P1 #7 — refresh token cannot cross client/principal."""

    def test_refresh_token_cannot_cross_client(self):
        store = TokenStore(db_path=Path("/tmp/test-refresh-binding.db"), secret=b"test-secret-key-minimum-32-bytes-ok!")
        refresh = store.issue_refresh_token("chatgpt", ["aether.read"], client_id="aether-principal-chatgpt")
        # Correct client -> ok
        assert store.consume_refresh_token(refresh, client_id="aether-principal-chatgpt") is not None

    def test_refresh_token_rejected_for_wrong_client(self):
        store = TokenStore(db_path=Path("/tmp/test-refresh-binding2.db"), secret=b"test-secret-key-minimum-32-bytes-ok!")
        refresh = store.issue_refresh_token("chatgpt", ["aether.read"], client_id="aether-principal-chatgpt")
        # Wrong client -> rejected
        assert store.consume_refresh_token(refresh, client_id="aether-principal-codex") is None


class TestJWTClaims:
    """P1 #9 — access token carries iss/aud claims, verified on decode."""

    def test_token_has_iss_aud(self):
        store = TokenStore(db_path=Path("/tmp/test-jwt-claims.db"), secret=b"test-secret-key-minimum-32-bytes-ok!")
        token, _ = store.issue_access_token("chatgpt", ["aether.read"])
        payload = store.verify_access_token(token)
        assert payload is not None
        assert payload["iss"] == os.getenv("AETHER_OAUTH_ISSUER", "https://aethers.my.id/oauth")
        assert payload["aud"] == os.getenv("AETHER_OAUTH_AUDIENCE", "https://aethers.my.id/mcp")


# ---------------------------------------------------------------------------
# P0-remaining (ChatGPT review, PR #60): browser consent must NOT require a
# secret header; governance is authoritative and fail-closed.
# ---------------------------------------------------------------------------

_AUTHORIZE_PARAMS = {
    "response_type": "code",
    "client_id": "aether-principal-chatgpt",
    "redirect_uri": "https://chatgpt.com/callback",
    "scope": "aether.read aether.diagnostic",
    "state": "state123",
    "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    "code_challenge_method": "S256",
}


def _extract_request_id(page_html: str) -> str:
    start = page_html.find("Request ID: ") + len("Request ID: ")
    end = page_html.find("<", start)
    return page_html[start:end].strip()


class TestFounderSessionCookie:
    """P0-remaining #1 — browser Founder approval via signed session cookie."""

    def test_login_mints_session_cookie(self, client):
        resp = client.post(
            "/oauth/login",
            data={"operator_token": "test-operator-token", "next": "/oauth/authorize"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        set_cookie = resp.headers.get("set-cookie", "")
        assert oauth_session.SESSION_COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie

    def test_login_wrong_token_rejected(self, client):
        resp = client.post(
            "/oauth/login",
            data={"operator_token": "wrong-token", "next": "/oauth/authorize"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert "set-cookie" not in resp.headers

    def test_login_rejects_external_redirect_target(self, client):
        resp = client.post(
            "/oauth/login",
            data={"operator_token": "test-operator-token", "next": "https://evil.example/phish"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/oauth/authorize"

    def test_logout_clears_session(self, client):
        client.post("/oauth/login", data={"operator_token": "test-operator-token"}, follow_redirects=False)
        resp = client.post("/oauth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "Max-Age=0" in resp.headers.get("set-cookie", "") or "expires=" in resp.headers.get("set-cookie", "").lower()

    def test_tampered_session_cookie_rejected(self, client):
        request_id = None
        page = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS).text
        request_id = _extract_request_id(page)
        resp = client.post(
            f"/oauth/approve/{request_id}",
            cookies={oauth_session.SESSION_COOKIE_NAME: "forged.token.value"},
        )
        assert resp.status_code == 401
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_sign_verify_session_roundtrip(self):
        token = oauth_session.sign_founder_session("founder")
        assert oauth_session.verify_founder_session(token) == "founder"
        assert oauth_session.verify_founder_session("not-a-real-token") is None


class TestBrowserConsentFlowE2E:
    """P0-remaining #4 — actual Founder browser approval end-to-end.

    authorize → login (session cookie) → browser approve (NO secret header)
    → governed proposal APPROVED → redirect with code → token exchange succeeds.
    """

    def test_consent_page_requires_sign_in_when_no_session(self, client):
        resp = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        assert resp.status_code == 200
        assert "Sign in to approve" in resp.text
        assert "/oauth/login" in resp.text

    def test_e2e_browser_approval_and_token_exchange(self, client):
        # 1. Login — mints the Founder session cookie in the browser jar.
        login = client.post(
            "/oauth/login",
            data={"operator_token": "test-operator-token", "next": "/oauth/authorize"},
            follow_redirects=False,
        )
        assert login.status_code == 302
        assert oauth_session.SESSION_COOKIE_NAME in login.headers.get("set-cookie", "")

        # 2. The browser (session cookie) now opens the consent page → Approve form.
        page = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        assert page.status_code == 200
        assert "Approve" in page.text
        request_id = _extract_request_id(page.text)

        # 3. Founder clicks Approve — plain form POST, NO secret header.
        approve = client.post(f"/oauth/approve/{request_id}", follow_redirects=False)
        assert approve.status_code == 302
        assert "code=" in approve.headers["location"]
        assert "state=state123" in approve.headers["location"]
        assert approval_inbox.get_approval_status(request_id) == "approved"

        # 4. Client exchanges the code for tokens.
        code = approve.headers["location"].split("code=")[1].split("&")[0]
        token = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert token.status_code == 200
        assert "access_token" in token.json()
        assert "refresh_token" in token.json()

    def test_e2e_browser_reject(self, client):
        client.post("/oauth/login", data={"operator_token": "test-operator-token"}, follow_redirects=False)
        page = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        request_id = _extract_request_id(page.text)
        reject = client.post(f"/oauth/reject/{request_id}", follow_redirects=False)
        assert reject.status_code == 302
        assert "error=access_denied" in reject.headers["location"]
        assert approval_inbox.get_approval_status(request_id) == "rejected"


class TestPkceRequiredAtToken:
    """P0 #5 — PKCE S256 is REQUIRED at the token endpoint.

    A missing code_verifier must be invalid_grant, never a silent pass.
    """

    def _get_code(self, client):
        resp = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        request_id = _extract_request_id(resp.text)
        approve = client.post(
            f"/oauth/approve/{request_id}",
            follow_redirects=False,
            headers={"X-Aether-Operator-Token": "test-operator-token"},
        )
        assert approve.status_code == 302
        return approve.headers["location"].split("code=")[1].split("&")[0]

    def test_missing_code_verifier_rejected(self, client):
        code = self._get_code(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            # no code_verifier at all
        })
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"
        assert "code_verifier" in resp.json()["error_description"]

    def test_correct_verifier_still_exchanges(self, client):
        code = self._get_code(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_replay_without_verifier_failure_does_not_consume(self, client):
        """A failed (verifier-less) exchange must NOT burn the code."""
        code = self._get_code(client)
        no_v = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
        })
        assert no_v.status_code == 400

        ok = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "https://chatgpt.com/callback",
            "client_id": "aether-principal-chatgpt",
            "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        })
        assert ok.status_code == 200


class TestRedirectUriAllowlist:
    """P0 #6 — redirect_uri must be on the principal's exact allowlist."""

    def test_authorize_allows_registered_redirect_uri(self, client):
        resp = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        assert resp.status_code == 200
        assert "Sign in to approve" in resp.text

    def test_authorize_rejects_unregistered_redirect_uri_before_pending(self, client):
        from aether_gateway.oauth_edge.server import get_store

        before = len(get_store().list_pending_auths())
        evil = dict(_AUTHORIZE_PARAMS, redirect_uri="https://evil.example/callback")
        resp = client.get("/oauth/authorize", params=evil)
        assert resp.status_code == 400
        assert "unauthorized_client" in resp.text
        # No pending authorization / consent was created for the rejected URI.
        assert len(get_store().list_pending_auths()) == before

    def test_authorize_rejects_other_principals_uri(self, client):
        """chatgpt must not be able to present codex's redirect_uri."""
        wrong = dict(_AUTHORIZE_PARAMS, redirect_uri="http://127.0.0.1:1455/auth/callback")
        resp = client.get("/oauth/authorize", params=wrong)
        assert resp.status_code == 400
        assert "unauthorized_client" in resp.text

    def test_registry_requires_redirect_uris(self):
        """Every principal MUST declare a redirect_uri allowlist (P0 #6)."""
        registry = get_registry()
        for principal in registry.all():
            assert principal.redirect_uris, f"principal {principal.id} has no redirect_uris"


class TestUnknownToolDenied:
    """P0 #7 — scope map is deny-by-default: unknown tools are never proxied."""

    def _issue_token(self, scopes=("aether.read",)):
        store = TokenStore(db_path=Path("/tmp/test-unknown-tool.db"), secret=b"test-secret-key-minimum-32-bytes-ok!")
        token, _ = store.issue_access_token("chatgpt", list(scopes))
        return token

    def test_unknown_tool_denied_403(self, client):
        token = self._issue_token()
        resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "totally_new_tool", "arguments": {}}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"] == "unclassified_tool"

    def test_unknown_tool_never_reaches_upstream(self, client):
        token = self._issue_token()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.request = AsyncMock()
            mock_client_cls.return_value = mock_client
            resp = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "unknown", "arguments": {}}},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
        mock_client.request.assert_not_called()

    def test_all_living_machine_tools_classified(self):
        """Every tool advertised by the Living MCP manifest has a scope map entry."""
        from aether_gateway.oauth_edge.server import LIVING_MACHINE_TOOLS, TOOL_SCOPE_MAP

        missing = sorted(LIVING_MACHINE_TOOLS - set(TOOL_SCOPE_MAP.keys()))
        assert not missing, f"advertised tools missing scope classification: {missing}"
        assert len(LIVING_MACHINE_TOOLS) == 22


class TestGovernanceFailClosed:
    """P0-remaining #2/#3 — Trusted Approval authoritative; no code without it."""

    _FOUNDER = {"X-Aether-Operator-Token": "test-operator-token"}

    def test_authorize_governance_submission_failure_fail_closed(self, client):
        from aether_gateway.oauth_edge.server import get_store

        before = len(get_store().list_pending_auths())
        with patch(
            "aether_gateway.oauth_edge.approval_inbox.submit_oauth_proposal",
            side_effect=RuntimeError("pending-action-store down"),
        ):
            resp = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        assert resp.status_code == 503
        assert "governance_unavailable" in resp.text
        # No pending request and no consent page survive a failed submission.
        assert len(get_store().list_pending_auths()) == before

    def test_approve_mark_decision_failure_issues_no_code(self, client):
        page = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        request_id = _extract_request_id(page.text)
        with patch(
            "aether_gateway.oauth_edge.approval_inbox.mark_decision",
            side_effect=RuntimeError("decision store down"),
        ):
            resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 503
        assert "code=" not in resp.headers.get("location", "")
        assert approval_inbox.get_approval_status(request_id) == "pending"

    def test_approve_without_linked_approval_issues_no_code(self, client):
        from aether_gateway.oauth_edge.server import get_store

        # A pending auth with no governed proposal (e.g. governance was never
        # submitted) must NOT be approvable.
        req = get_store().create_pending_auth(
            principal_id="chatgpt",
            client_id="aether-principal-chatgpt",
            redirect_uri="https://chatgpt.com/callback",
            scopes=["aether.read"],
            code_challenge="abc123",
            code_challenge_method="S256",
            state="s",
        )
        resp = client.post(f"/oauth/approve/{req.request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 503
        assert "code=" not in resp.headers.get("location", "")

    def test_approve_rejected_proposal_issues_no_code(self, client):
        # If the governed proposal was already rejected, approve must NOT mint a
        # code (mark_decision returns the existing REJECTED record).
        page = client.get("/oauth/authorize", params=_AUTHORIZE_PARAMS)
        request_id = _extract_request_id(page.text)
        rejected = client.post(f"/oauth/reject/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert rejected.status_code == 302
        resp = client.post(f"/oauth/approve/{request_id}", follow_redirects=False, headers=self._FOUNDER)
        assert resp.status_code == 409
        assert "code=" not in resp.headers.get("location", "")
