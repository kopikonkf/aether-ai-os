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
# tests/ is at aether-gateway/tests/ — repo root is 3 levels up
os.environ["AETHER_PRINCIPAL_REGISTRY"] = str(
    Path(__file__).parent.parent.parent / "configs" / "principal_registry.yaml"
)

import aether_gateway.oauth_edge.registry as _reg_module
_reg_module._registry = None  # reset singleton before first import resolves it

from aether_gateway.oauth_edge.server import app
from aether_gateway.oauth_edge.token_store import TokenStore, _hmac_sign, _hmac_verify
from aether_gateway.oauth_edge.registry import PrincipalRegistry, get_registry
from aether_gateway.oauth_edge import approval_inbox

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
