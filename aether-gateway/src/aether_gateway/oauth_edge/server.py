"""Aether MCP OAuth Edge — FastAPI application.

ADR-0056: OAuth 2.0 Authorization Server facade in front of Living Machine MCP.

Endpoints:
  GET  /.well-known/oauth-authorization-server   RFC 8414 discovery
  POST /oauth/register                            RFC 7591 client registration (pre-approved only)
  GET  /oauth/authorize                           Authorization endpoint (HTML Founder consent, GitHub-OAuth style)
  GET  /oauth/login                               Founder operator login page (browses session)
  POST /oauth/login                               Founder operator login (sets signed session cookie)
  POST /oauth/logout                              Clears the Founder session cookie
  POST /oauth/approve/<request_id>               Founder approves (operator header OR browser session cookie)
  POST /oauth/reject/<request_id>                Founder rejects (operator header OR browser session cookie)
  POST /oauth/token                               Token endpoint (code exchange + refresh)
  POST /oauth/revoke                              Token revocation
  GET  /oauth/pending                             List pending authorization requests (internal)
  ANY  /mcp                                       MCP proxy with token validation
  GET  /health                                    Health check

Approval security (P0 #1 + P0-remaining): the HTML consent page is the ONLY
approval surface (no Telegram). Approving/rejecting an authorization requires
the trusted Founder operator identity — either the ``X-Aether-Operator-Token``
header (API/CLI clients) or a short-lived signed session cookie minted by
``POST /oauth/login`` (browser Founder; a plain HTML form cannot carry a secret
header). Each authorize additionally submits a governed ActionProposal
(operation oauth.authorize) into the shared Trusted Approval Inbox, and that
submission is AUTHORITATIVE: if the governed proposal cannot be created, the
authorization does not proceed (503, no consent page, no code). Issuing an
authorization code requires the governed proposal to be durably APPROVED —
governance failure is never treated as approval (fail-closed, P0-remaining).
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import time
from typing import Any, Optional

import httpx
import uvicorn
from fastapi import FastAPI, Form, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from aether.contracts import ApprovalStatus
from aether_gateway.approvals.auth import TrustedOperator

from .audit import (
    log_auth_approved,
    log_auth_rejected,
    log_auth_requested,
    log_mcp_proxy,
    log_scope_denied,
    log_token_issued,
    log_token_refreshed,
    log_token_revoked,
)
from . import approval_inbox, session
from .registry import get_registry
from .token_store import TokenStore

# ---------------------------------------------------------------------------
# Scope enforcement — Tool-to-Scope mapping (ADR-0056 P0 #2)
# ---------------------------------------------------------------------------

TOOL_SCOPE_MAP: dict[str, list[str]] = {
    # READ tools (aether.read)
    "file_read": ["aether.read"],
    "file_hash": ["aether.read"],
    "workspace_tree": ["aether.read"],
    "workspace_list": ["aether.read"],
    "git_status": ["aether.read"],
    "git_log": ["aether.read"],
    "git_diff": ["aether.read"],
    "logs_tail": ["aether.read"],
    "runtime_status": ["aether.read"],
    "runtime_adapters": ["aether.read"],
    "service_status": ["aether.read"],
    "aether_living_capabilities": ["aether.read"],
    # DIAGNOSTIC tools (aether.diagnostic)
    "run_verification": ["aether.diagnostic"],
    "runtime_telemetry": ["aether.diagnostic"],
    # MUTATE tools (aether.mutate — operator token required)
    "workspace_edit": ["aether.mutate"],
    "decide_and_resume": ["aether.mutate"],
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PUBLIC_BASE_URL = os.getenv("AETHER_OAUTH_PUBLIC_BASE_URL", "https://aethers.my.id")
MCP_UPSTREAM = os.getenv("AETHER_MCP_UPSTREAM", "http://127.0.0.1:8787")
MCP_TOKEN = os.getenv("AETHER_MCP_TOKEN", "")
# P1 #8: OAuth edge administration (list pending) uses a SEPARATE credential —
# never the shared MCP upstream token.
OAUTH_ADMIN_TOKEN = os.getenv("AETHER_OAUTH_ADMIN_TOKEN", "")
PORT = int(os.getenv("AETHER_OAUTH_EDGE_PORT", "8789"))

app = FastAPI(title="Aether MCP OAuth Edge", version="1.0.0", docs_url=None, redoc_url=None)

# Module-level token store — initialised once at first request to allow env to be set
_store: Optional[TokenStore] = None


def get_store() -> TokenStore:
    global _store
    if _store is None:
        _store = TokenStore()
    return _store


# ---------------------------------------------------------------------------
# RFC 8414 — OAuth Authorization Server Metadata
# ---------------------------------------------------------------------------

@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> JSONResponse:
    return JSONResponse({
        "issuer": PUBLIC_BASE_URL,
        "authorization_endpoint": f"{PUBLIC_BASE_URL}/oauth/authorize",
        "token_endpoint": f"{PUBLIC_BASE_URL}/oauth/token",
        "registration_endpoint": f"{PUBLIC_BASE_URL}/oauth/register",
        "revocation_endpoint": f"{PUBLIC_BASE_URL}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["aether.read", "aether.diagnostic", "aether.mutate"],
    })


# ---------------------------------------------------------------------------
# RFC 7591 — Dynamic Client Registration
# ---------------------------------------------------------------------------

@app.post("/oauth/register")
async def register_client(request: Request) -> JSONResponse:
    """Pre-approved client registration (RFC 7591 shape, not unrestricted).

    P1 #6: this is NOT arbitrary dynamic registration — only client_ids that
    already exist in configs/principal_registry.yaml are accepted. Unknown
    clients are rejected with invalid_client_metadata.
    """
    body = await request.json()
    client_id = body.get("client_id", "")
    registry = get_registry()
    principal = registry.get_by_client_id(client_id)
    if principal is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_client_metadata",
                "error_description": (
                    f"client_id '{client_id}' is not registered in the Aether principal registry. "
                    "Contact the Founder to add a new principal entry."
                ),
            },
        )
    # Return a minimal RFC 7591 response
    return JSONResponse({
        "client_id": principal.client_id,
        "client_name": principal.display_name,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(sorted(principal.allowed_scopes)),
    }, status_code=201)


# ---------------------------------------------------------------------------
# Authorization endpoint
# ---------------------------------------------------------------------------

@app.get("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
) -> HTMLResponse:
    """
    OAuth Authorization endpoint.
    Validates the request, creates a pending auth record, and renders the
    Founder approval page (similar to the GitHub OAuth consent screen).
    """
    registry = get_registry()
    principal = registry.get_by_client_id(client_id)

    if response_type != "code":
        return HTMLResponse(_error_page("unsupported_response_type", "Only 'code' is supported."), status_code=400)

    if principal is None:
        return HTMLResponse(_error_page("unauthorized_client", f"Unknown client_id: {client_id}"), status_code=400)

    if not redirect_uri:
        return HTMLResponse(_error_page("invalid_request", "redirect_uri is required."), status_code=400)

    if not code_challenge:
        return HTMLResponse(_error_page("invalid_request", "PKCE code_challenge is required."), status_code=400)

    # P1 #5: enforce S256 PKCE method — reject plain otherwise
    if code_challenge_method != "S256":
        return HTMLResponse(_error_page("invalid_request", "Only PKCE S256 is supported."), status_code=400)

    requested_scopes = [s.strip() for s in scope.split() if s.strip()]
    effective_scopes = principal.effective_scopes(requested_scopes)

    store = get_store()
    pending = store.create_pending_auth(
        principal_id=principal.id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=effective_scopes,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        state=state,
    )

    # P0 #1 + P0-remaining (fail-closed): mirror the authorization into Aether's
    # governed Trusted Approval Inbox. The submission is AUTHORITATIVE — if the
    # proposal cannot be created, the authorization request is dropped and the
    # consent page is not shown. Governance unavailable must never degrade into
    # an approvable request.
    try:
        approval_id, _ = approval_inbox.submit_oauth_proposal(
            request_id=pending.request_id,
            principal_id=principal.id,
            client_id=client_id,
            scopes=effective_scopes,
            redirect_uri=redirect_uri,
            state=state,
        )
    except Exception as exc:
        store.cancel_pending_auth(pending.request_id)
        return HTMLResponse(
            _error_page(
                "governance_unavailable",
                "The authorization could not be recorded in the Trusted Approval Inbox; "
                f"please retry. ({exc.__class__.__name__})",
            ),
            status_code=503,
        )
    pending.approval_id = approval_id
    log_auth_requested(pending.request_id, principal.id, effective_scopes)

    authenticated = _current_founder(request) is not None
    # Relative same-origin target so the post-login redirect carries the original
    # authorize query (client_id, code_challenge, state, ...) and re-renders the
    # consent page for the SAME authorization request.
    query = request.url.query
    next_url = f"{request.url.path}?{query}" if query else request.url.path
    return HTMLResponse(
        _approval_page(
            pending.request_id,
            principal,
            effective_scopes,
            authenticated=authenticated,
            next_url=next_url,
        )
    )


def _approval_page(
    request_id: str,
    principal: Any,
    scopes: list[str],
    authenticated: bool,
    next_url: str,
) -> str:
    scope_rows = "".join(
        f"<li><code>{s}</code> — {_scope_description(s)}</li>" for s in scopes
    )
    if authenticated:
        actions = f"""
  <div class="actions">
    <form method="POST" action="/oauth/approve/{request_id}" style="flex:1">
      <button class="btn btn-approve" type="submit">Approve</button>
    </form>
    <form method="POST" action="/oauth/reject/{request_id}" style="flex:1">
      <button class="btn btn-reject" type="submit">Reject</button>
    </form>
  </div>"""
    else:
        actions = f"""
  <div class="login">
    <p>Sign in with your Founder operator token to review this request.</p>
    <form method="POST" action="/oauth/login" style="display:flex;flex-direction:column;gap:8px">
      <input type="hidden" name="next" value="{html.escape(next_url, quote=True)}">
      <input type="password" name="operator_token" placeholder="Founder operator token"
             autocomplete="current-password" required />
      <button class="btn btn-approve" type="submit">Sign in to approve</button>
    </form>
  </div>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aether — Authorize {principal.display_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117; color: #c9d1d9; min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 12px;
    padding: 32px; max-width: 480px; width: 100%;
  }}
  .logo {{
    font-size: 22px; font-weight: 700; color: #58a6ff;
    letter-spacing: -0.5px; margin-bottom: 4px;
  }}
  .logo span {{ color: #7ee787; }}
  h1 {{ font-size: 18px; font-weight: 600; margin: 24px 0 8px; color: #f0f6fc; }}
  .principal {{
    display: flex; align-items: center; gap: 12px;
    background: #0d1117; border: 1px solid #30363d; border-radius: 8px;
    padding: 12px 16px; margin: 16px 0;
  }}
  .principal-icon {{
    width: 40px; height: 40px; background: #1f6feb; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; flex-shrink: 0;
  }}
  .principal-name {{ font-weight: 600; color: #f0f6fc; }}
  .principal-id {{ font-size: 12px; color: #8b949e; }}
  .scopes {{ margin: 16px 0; }}
  .scopes h2 {{ font-size: 13px; font-weight: 600; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .scopes ul {{ list-style: none; }}
  .scopes li {{
    padding: 8px 12px; background: #0d1117; border: 1px solid #30363d;
    border-radius: 6px; margin-bottom: 6px; font-size: 13px;
  }}
  .scopes code {{ color: #79c0ff; background: #1f2428; padding: 1px 6px; border-radius: 4px; }}
  .warning {{
    background: #3d1f00; border: 1px solid #d29922; border-radius: 6px;
    padding: 10px 14px; font-size: 13px; color: #e3b341; margin: 16px 0;
  }}
  .actions {{ display: flex; gap: 12px; margin-top: 24px; }}
  .login {{ margin-top: 20px; }}
  .login p {{ font-size: 13px; color: #8b949e; margin-bottom: 10px; }}
  .login input {{
    background: #0d1117; border: 1px solid #30363d; color: #c9d1d9;
    padding: 10px 12px; border-radius: 6px; font-size: 14px; width: 100%;
  }}
  .btn {{
    flex: 1; padding: 10px; border-radius: 6px; font-size: 14px;
    font-weight: 600; cursor: pointer; border: none;
  }}
  .btn-approve {{ background: #238636; color: #fff; }}
  .btn-approve:hover {{ background: #2ea043; }}
  .btn-reject {{ background: transparent; color: #f85149; border: 1px solid #f85149; }}
  .btn-reject:hover {{ background: #3d1f20; }}
  .request-id {{ font-size: 11px; color: #484f58; margin-top: 16px; text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Aether <span>OS</span></div>
  <h1>Authorize external access</h1>
  <div class="principal">
    <div class="principal-icon">&#127744;</div>
    <div>
      <div class="principal-name">{principal.display_name}</div>
      <div class="principal-id">client_id: {principal.client_id}</div>
    </div>
  </div>
  <div class="scopes">
    <h2>Requesting permissions</h2>
    <ul>{scope_rows}</ul>
  </div>
  <div class="warning">
    &#9888; Only approve if you initiated this connection from {principal.display_name}.
  </div>
  {actions}
  <div class="request-id">Request ID: {request_id}</div>
</div>
</body>
</html>"""


def _scope_description(scope: str) -> str:
    return {
        "aether.read": "Read files, git status, logs, runtime status, service health",
        "aether.diagnostic": "Run verifications, read telemetry and diagnostics",
        "aether.mutate": "Submit workspace edits and mutations (Founder approval required per action)",
    }.get(scope, scope)


def _error_page(error: str, description: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Aether — Authorization Error</title>
<style>body{{font-family:sans-serif;background:#0d1117;color:#c9d1d9;display:flex;align-items:center;justify-content:center;min-height:100vh}}
.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:32px;max-width:400px}}
h1{{color:#f85149;margin-bottom:8px}}p{{color:#8b949e;font-size:14px}}</style></head>
<body><div class="card"><h1>{error}</h1><p>{description}</p></div></body></html>"""


def _login_page(error: Optional[str] = None) -> str:
    error_html = f'<p class="login-error">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Aether — Founder Sign In</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117; color: #c9d1d9; min-height: 100vh;
    display: flex; align-items: center; justify-content: center;
  }}
  .card {{
    background: #161b22; border: 1px solid #30363d; border-radius: 12px;
    padding: 32px; max-width: 380px; width: 100%;
  }}
  .logo {{ font-size: 22px; font-weight: 700; color: #58a6ff; margin-bottom: 24px; }}
  .logo span {{ color: #7ee787; }}
  label {{ font-size: 13px; font-weight: 600; color: #8b949e; display: block; margin-bottom: 8px; }}
  input {{
    background: #0d1117; border: 1px solid #30363d; color: #c9d1d9;
    padding: 10px 12px; border-radius: 6px; font-size: 14px; width: 100%; margin-bottom: 16px;
  }}
  button {{
    width: 100%; padding: 10px; border-radius: 6px; font-size: 14px; font-weight: 600;
    cursor: pointer; border: none; background: #238636; color: #fff;
  }}
  button:hover {{ background: #2ea043; }}
  .login-error {{ color: #f85149; font-size: 13px; margin-bottom: 12px; }}
</style></head>
<body><div class="card">
  <div class="logo">Aether <span>OS</span></div>
  {error_html}
  <form method="POST" action="/oauth/login">
    <label for="operator_token">Founder operator token</label>
    <input id="operator_token" type="password" name="operator_token"
           autocomplete="current-password" required />
    <button type="submit">Sign in</button>
  </form>
</div></body></html>"""


def _current_founder(request: Request) -> Optional[TrustedOperator]:
    """Return the authenticated Founder from the browser session cookie, else None."""
    token = request.cookies.get(session.SESSION_COOKIE_NAME)
    if not token:
        return None
    principal = session.verify_founder_session(token)
    if principal is None:
        return None
    return TrustedOperator(principal=principal, channel="oauth-session")


def _authenticate_founder(
    request: Request,
    x_aether_operator_token: Optional[str],
) -> Optional[TrustedOperator]:
    """Resolve the Founder operator — secret header (API clients) or session cookie (browser).

    The browser consent page cannot carry the secret header, so the browser
    path authenticates via the signed session cookie minted by POST /oauth/login.
    """
    if x_aether_operator_token:
        try:
            return approval_inbox.authenticate_operator(x_aether_operator_token)
        except Exception:
            return None
    return _current_founder(request)


def _operator_rejection_status() -> int:
    """401 wrong/missing credential; 503 when the operator identity is not configured."""
    return 503 if not approval_inbox.operator_configured() else 401


def _safer_redirect_target(target: str) -> str:
    """Only allow same-origin relative paths for post-login redirects (open-redirect guard)."""
    if not target.startswith("/") or target.startswith("//"):
        return "/oauth/authorize"
    return target


@app.get("/oauth/login")
async def oauth_login_page() -> HTMLResponse:
    return HTMLResponse(_login_page())


@app.post("/oauth/login")
async def oauth_login(
    request: Request,
    operator_token: str = Form(...),
    next: str = Form(""),
) -> Response:
    """Founder operator login — validates the operator token and mints a session cookie.

    This is the ONLY place the operator token is accepted from a browser. The
    token itself is never stored; only a short-lived, HttpOnly, signed session
    cookie is set, and it is accepted exclusively by the consent decision
    endpoints (POST /oauth/approve and POST /oauth/reject).
    """
    try:
        operator = approval_inbox.authenticate_operator(operator_token)
    except Exception:
        status = 503 if not approval_inbox.operator_configured() else 401
        return HTMLResponse(_login_page(error="Invalid Founder operator token."), status_code=status)

    cookie_value = session.sign_founder_session(operator.principal)
    target = _safer_redirect_target(next) or "/oauth/authorize"
    response = RedirectResponse(url=target, status_code=302)
    response.set_cookie(
        key=session.SESSION_COOKIE_NAME,
        value=cookie_value,
        max_age=session.SESSION_TTL,
        httponly=True,
        secure=session.SESSION_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@app.post("/oauth/logout")
async def oauth_logout() -> Response:
    response = RedirectResponse(url="/oauth/login", status_code=302)
    response.delete_cookie(session.SESSION_COOKIE_NAME, path="/")
    return response


# ---------------------------------------------------------------------------
# Founder approval / rejection actions
# ---------------------------------------------------------------------------

@app.post("/oauth/approve/{request_id}")
async def approve_auth(
    request: Request,
    request_id: str,
    x_aether_operator_token: Optional[str] = Header(default=None),
) -> Response:
    """Founder approves — generate auth code and redirect to client.

    Founder authentication is either the trusted ``X-Aether-Operator-Token``
    header (API/CLI clients) or the browser session cookie minted by
    ``POST /oauth/login`` (the consent page — a plain HTML form cannot carry a
    secret header). See ``_authenticate_founder``.

    Governance is authoritative and fail-closed: a code is issued ONLY after the
    linked governed proposal is durably APPROVED. If ``mark_decision`` fails or
    the proposal is not APPROVED, no authorization code is issued (503/409).
    """
    operator = _authenticate_founder(request, x_aether_operator_token)
    if operator is None:
        return JSONResponse({"error": "invalid_operator_token"}, status_code=_operator_rejection_status())

    store = get_store()
    pending = store.get_pending_auth(request_id)
    if pending is None:
        return HTMLResponse(_error_page("invalid_request", "Authorization request not found or expired."), status_code=400)

    if not pending.approval_id:
        return HTMLResponse(
            _error_page(
                "governance_unavailable",
                "This request has no linked governed approval; it cannot be authorized.",
            ),
            status_code=503,
        )

    # Authoritative, fail-closed governed decision. Any failure means NO code.
    try:
        decided = approval_inbox.mark_decision(
            pending.approval_id,
            approved=True,
            principal=operator.principal,
            reason="OAuth authorization approved by Founder via HTML consent",
        )
    except Exception as exc:
        return HTMLResponse(
            _error_page(
                "governance_failed",
                f"The governed approval could not be recorded; no code was issued. ({exc.__class__.__name__})",
            ),
            status_code=503,
        )

    # Fail-closed: only a durably APPROVED governed proposal yields a code.
    if decided.status != ApprovalStatus.APPROVED:
        return HTMLResponse(
            _error_page(
                "not_approved",
                f"Governed approval ended in '{decided.status.value}' — no code was issued.",
            ),
            status_code=409,
        )

    code = store.approve_auth(request_id)
    if code is None:
        return HTMLResponse(_error_page("invalid_request", "Could not approve request."), status_code=400)

    pending.approving_principal = operator.principal
    log_auth_approved(request_id, pending.principal_id, operator.principal)

    # Redirect to client with code
    sep = "&" if "?" in pending.redirect_uri else "?"
    redirect_url = f"{pending.redirect_uri}{sep}code={code}&state={pending.state}"
    return RedirectResponse(url=redirect_url, status_code=302)


@app.post("/oauth/reject/{request_id}")
async def reject_auth(
    request: Request,
    request_id: str,
    x_aether_operator_token: Optional[str] = Header(default=None),
) -> Response:
    """Founder rejects — redirect with error.

    Founder authentication via operator header or browser session cookie.
    Governance is authoritative: the linked proposal must be durably REJECTED
    before the client is redirected with an access_denied error.
    """
    operator = _authenticate_founder(request, x_aether_operator_token)
    if operator is None:
        return JSONResponse({"error": "invalid_operator_token"}, status_code=_operator_rejection_status())

    store = get_store()
    pending = store.get_pending_auth(request_id)
    if pending is None:
        return HTMLResponse(_error_page("invalid_request", "Authorization request not found or expired."), status_code=400)

    if not pending.approval_id:
        return HTMLResponse(
            _error_page(
                "governance_unavailable",
                "This request has no linked governed approval; it cannot be rejected.",
            ),
            status_code=503,
        )

    try:
        decided = approval_inbox.mark_decision(
            pending.approval_id,
            approved=False,
            principal=operator.principal,
            reason="OAuth authorization rejected by Founder via HTML consent",
        )
    except Exception as exc:
        return HTMLResponse(
            _error_page(
                "governance_failed",
                f"The governed rejection could not be recorded. ({exc.__class__.__name__})",
            ),
            status_code=503,
        )

    if decided.status != ApprovalStatus.REJECTED:
        return HTMLResponse(
            _error_page(
                "not_rejected",
                f"Governed decision ended in '{decided.status.value}' — no rejection was recorded.",
            ),
            status_code=409,
        )

    store.reject_auth(request_id)
    pending.approving_principal = operator.principal
    log_auth_rejected(request_id, pending.principal_id, operator.principal)

    sep = "&" if "?" in pending.redirect_uri else "?"
    redirect_url = f"{pending.redirect_uri}{sep}error=access_denied&state={pending.state}"
    return RedirectResponse(url=redirect_url, status_code=302)


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------

@app.post("/oauth/token")
async def token_endpoint(
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
) -> JSONResponse:
    store = get_store()

    if grant_type == "authorization_code":
        return await _handle_code_exchange(store, code, redirect_uri, client_id, code_verifier)
    elif grant_type == "refresh_token":
        return await _handle_refresh(store, refresh_token, client_id or "")
    else:
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


async def _handle_code_exchange(
    store: TokenStore,
    code: Optional[str],
    redirect_uri: Optional[str],
    client_id: Optional[str],
    code_verifier: Optional[str],
) -> JSONResponse:
    if not code:
        return JSONResponse({"error": "invalid_request", "error_description": "code is required"}, status_code=400)

    # P0 #4: Non-destructive lookup — validate all binding + PKCE BEFORE consuming.
    pending = store.get_pending_auth_by_code(code)
    if pending is None:
        return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired authorization code"}, status_code=400)

    # P0 #3: Validate client_id and redirect_uri binding to the authorization request.
    if pending.client_id != client_id:
        return JSONResponse({"error": "invalid_grant", "error_description": "client_id mismatch"}, status_code=400)
    if pending.redirect_uri != redirect_uri:
        return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)

    # Validate PKCE S256 (before consuming code — P0 #4)
    if pending.code_challenge_method == "S256" and code_verifier:
        import base64
        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        if challenge != pending.code_challenge:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

    # All validations passed — now atomically consume the code (single-use).
    consumed = store.consume_auth_code(code)
    if consumed is None:
        return JSONResponse({"error": "invalid_grant", "error_description": "Authorization code already used"}, status_code=400)

    access_token, expires_in = store.issue_access_token(pending.principal_id, pending.scopes)
    refresh_token_plain = store.issue_refresh_token(pending.principal_id, pending.scopes, client_id=pending.client_id)

    log_token_issued(pending.principal_id, pending.scopes, expires_in)

    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh_token_plain,
        "scope": " ".join(pending.scopes),
    })


async def _handle_refresh(store: TokenStore, refresh_token: Optional[str], client_id: str = "") -> JSONResponse:
    if not refresh_token:
        return JSONResponse({"error": "invalid_request", "error_description": "refresh_token is required"}, status_code=400)

    result = store.consume_refresh_token(refresh_token, client_id=client_id)
    if result is None:
        return JSONResponse({"error": "invalid_grant", "error_description": "Invalid or expired refresh token"}, status_code=400)

    principal_id, scopes = result
    access_token, expires_in = store.issue_access_token(principal_id, scopes)
    new_refresh = store.issue_refresh_token(principal_id, scopes, client_id=client_id)

    log_token_refreshed(principal_id, scopes)

    return JSONResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": new_refresh,
        "scope": " ".join(scopes),
    })


# ---------------------------------------------------------------------------
# Token revocation (RFC 7009)
# ---------------------------------------------------------------------------

@app.post("/oauth/revoke")
async def revoke_token(
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
) -> JSONResponse:
    # For now just try to revoke as refresh token
    store = get_store()
    result = store.consume_refresh_token(token)
    if result:
        principal_id, _ = result
        log_token_revoked(principal_id, "explicit_revocation")
    # RFC 7009: always return 200 regardless
    return JSONResponse({})


# ---------------------------------------------------------------------------
# Internal: list pending authorization requests
# ---------------------------------------------------------------------------

@app.get("/oauth/pending")
async def list_pending(authorization: Optional[str] = Header(None)) -> JSONResponse:
    """Internal endpoint — list pending Founder approval requests.

    Protected by MCP token to keep this internal-only.
    """
    if not _verify_internal_token(authorization):
        raise HTTPException(status_code=401, detail="authentication_required")

    store = get_store()
    pending = store.list_pending_auths()
    return JSONResponse({
        "pending": [
            {
                "request_id": p.request_id,
                "principal_id": p.principal_id,
                "display_name": _get_display_name(p.principal_id),
                "scopes": p.scopes,
                "created_at": p.created_at,
                "age_seconds": int(time.time() - p.created_at),
            }
            for p in pending
        ]
    })


def _verify_internal_token(authorization: Optional[str]) -> bool:
    if not authorization:
        return False
    import hmac as _hmac
    if not authorization.lower().startswith("bearer "):
        return False
    token = authorization[7:].strip()
    expected = OAUTH_ADMIN_TOKEN
    if not expected:
        return False
    return _hmac.compare_digest(token, expected)


def _get_display_name(principal_id: str) -> str:
    registry = get_registry()
    p = registry.get_by_id(principal_id)
    return p.display_name if p else principal_id


# ---------------------------------------------------------------------------
# MCP Proxy
# ---------------------------------------------------------------------------

@app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.api_route("/mcp/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS"])
async def mcp_proxy(request: Request, path: str = "") -> Response:
    """Validate Bearer token, inject principal headers, proxy to MCP upstream."""
    authorization = request.headers.get("authorization", "")

    if not authorization.lower().startswith("bearer "):
        return JSONResponse({"error": "authentication_required"}, status_code=401)

    token_str = authorization[7:].strip()
    store = get_store()
    payload = store.verify_access_token(token_str)

    if payload is None:
        return JSONResponse({"error": "invalid_token"}, status_code=401)

    principal_id: str = payload.get("principal_id", "unknown")
    scopes: list[str] = payload.get("scopes", [])

    # Scope enforcement (P0 #2) — check tool against TOOL_SCOPE_MAP BEFORE proxy
    body = await request.body()
    if body and request.method == "POST":
        try:
            body_json = json.loads(body)
            method = body_json.get("method", "")
            # MCP tools/call method: params.name = tool name
            if method == "tools/call":
                tool_name = body_json.get("params", {}).get("name", "")
                required_scopes = TOOL_SCOPE_MAP.get(tool_name, [])
                if required_scopes and not all(s in scopes for s in required_scopes):
                    log_scope_denied(principal_id, tool_name)
                    return JSONResponse(
                        {"error": "insufficient_scope", "error_description": f"Tool '{tool_name}' requires {required_scopes}, token has {scopes}"},
                        status_code=403
                    )
        except Exception:
            pass  # Body parse error → let upstream handle malformed request

    # Build upstream URL
    upstream_path = f"/mcp/{path}" if path else "/mcp"
    upstream_url = f"{MCP_UPSTREAM}{upstream_path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Forward headers, replacing Authorization with MCP token
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("authorization", "host", "content-length")
    }
    forward_headers["Authorization"] = f"Bearer {MCP_TOKEN}"
    forward_headers["X-Aether-Principal-Id"] = principal_id
    forward_headers["X-Aether-Principal-Scopes"] = " ".join(scopes)

    body = await request.body()

    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream_resp = await client.request(
            method=request.method,
            url=upstream_url,
            headers=forward_headers,
            content=body,
        )

    log_mcp_proxy(principal_id, scopes, request.method, upstream_path, upstream_resp.status_code)

    # Stream response back
    return Response(
        content=upstream_resp.content,
        status_code=upstream_resp.status_code,
        headers={
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in ("content-encoding", "transfer-encoding", "content-length")
        },
        media_type=upstream_resp.headers.get("content-type"),
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "service": "aether-mcp-oauth-edge",
        "version": "1.0.0",
        "mcp_upstream": MCP_UPSTREAM,
        "public_base": PUBLIC_BASE_URL,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    uvicorn.run(
        "aether_gateway.oauth_edge.server:app",
        host="127.0.0.1",
        port=PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
