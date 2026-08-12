"""Wiring between the OAuth Edge and Aether's governed Trusted Approval Inbox.

P0 #1 (ADR-0056 hardening): Founder OAuth authorization must NOT be issued by an
unauthenticated network POST. Anyone holding an authorization request_id must not,
by themselves, be able to mint an authorization code.

To close that hole while preserving the GitHub-OAuth-style HTML consent flow:

  * Each ``/oauth/authorize`` request submits a governed ``ActionProposal``
    (operation ``oauth.authorize``) into the shared ``PendingActionStore`` used by
    Aether's HTML approval inbox, so the request surfaces as a real governed
    action in the Gateway ``/approvals`` page. The submission is authoritative:
    if it fails, the authorization must not proceed (fail-closed).
  * Issuing the authorization code is gated by an authenticated Founder decision.
    This module reuses the SAME ``OperatorAuthenticator`` (``AETHER_OPERATOR_TOKEN``)
    trusted identity that the Gateway uses for every HTML approval decision, so a
    random caller holding only request_id can no longer approve.
  * ``mark_decision`` is authoritative and fail-closed: the Edge only issues a
    code after the governed proposal is durably APPROVED. Governance failure is
    never treated as approval.

The approval channel is the HTML approval surface only (never Telegram). A
browser Founder authenticates once via an operator-token login that mints a
short-lived signed session cookie (``oauth_edge.session``); the consent page's
Approve/Reject forms then POST with that cookie instead of a secret header.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from aether.actions import PendingActionStore
from aether.contracts import (
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    PendingAction,
)
from aether_gateway.approvals.auth import OperatorAuthenticator, TrustedOperator

# A governed OAuth authorization is short-lived; it must stay in step with the
# in-memory AUTH_CODE_TTL of the TokenStore.
_DEFAULT_TTL = 300


def _governance_db_path() -> Path:
    env_path = os.getenv("AETHER_OAUTH_GOVERNANCE_DB", "").strip()
    if env_path:
        return Path(env_path)
    aether_home = os.getenv("AETHER_HOME", r"C:\ProgramData\Aether")
    return Path(aether_home) / "governance" / "pending-actions.sqlite3"


def _ttl_seconds() -> int:
    try:
        return max(1, int(os.getenv("AETHER_OAUTH_APPROVAL_TTL", str(_DEFAULT_TTL))))
    except (TypeError, ValueError):
        return _DEFAULT_TTL


_store: Optional[PendingActionStore] = None
_operator_auth: Optional[OperatorAuthenticator] = None


def _get_store() -> PendingActionStore:
    global _store
    if _store is None:
        _store = PendingActionStore(_governance_db_path(), default_ttl_seconds=_ttl_seconds())
    return _store


def _get_operator_auth() -> OperatorAuthenticator:
    global _operator_auth
    if _operator_auth is None:
        _operator_auth = OperatorAuthenticator()
    return _operator_auth


def reset() -> None:
    """Forget cached singletons. Used by tests for isolation."""
    global _store, _operator_auth
    _store = None
    _operator_auth = None


def authenticate_operator(token: Optional[str]) -> TrustedOperator:
    """Validate a Founder/operator credential.

    Raises `aether_gateway.approvals.auth.OperatorAuthError` on failure or when
    the trusted operator token is not configured.
    """
    return _get_operator_auth().authenticate(token, channel="http")


def operator_configured() -> bool:
    return _get_operator_auth().configured


def submit_oauth_proposal(
    *,
    request_id: str,
    principal_id: str,
    client_id: str,
    scopes: list[str],
    redirect_uri: str,
    state: str,
) -> tuple[str, bool]:
    """Submit a governed `oauth.authorize` proposal to the Trusted Approval Inbox.

    The returned `approval_id` links the governable pending action to the
    in-memory OAuth authorization request. Returns (approval_id, created).
    """
    metadata = {
        "oauth_request_id": request_id,
        "principal_id": principal_id,
        "client_id": client_id,
        "scopes": list(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "channel": "oauth",
    }
    proposal = ActionProposal(
        target=ActionTarget.TOOL,
        operation="oauth.authorize",
        reason=f"Authorize principal '{principal_id}' (client '{client_id}') to connect via OAuth.",
        risk=ActionRisk.MEDIUM,
        reversible=True,
        required_scopes=(ActionScope.READ,),
        metadata=metadata,
    )
    pending, created = _get_store().create_or_get(
        proposal,
        request_channel="oauth",
        requested_by=principal_id,
        ttl_seconds=_ttl_seconds(),
    )
    return pending.approval_id, created


def find_approval_id_by_request(request_id: str) -> Optional[str]:
    """Map an OAuth request_id to its governed approval_id (if any)."""
    store = _get_store()
    store.expire_due()
    for pending in store.list():
        if str(pending.proposal.metadata.get("oauth_request_id", "")) == str(request_id):
            return pending.approval_id
    return None


def mark_decision(
    approval_id: str,
    *,
    approved: bool,
    principal: str,
    reason: str,
) -> PendingAction:
    """Record the Founder decision on an oauth.authorize proposal.

    Otoritative and fail-closed: this is the durable decision that authorizes
    (or rejects) an OAuth authorization. Any failure (missing/expired proposal,
    store error, integrity error) RAISES — the caller must then NOT issue an
    authorization code. Governance unavailable must never degrade into
    auto-approval.
    """
    return _get_store().decide(
        approval_id,
        approved=approved,
        principal=principal,
        reason=reason,
        channel="http",
    )


def get_approval_status(request_id: str) -> Optional[str]:
    """Best-effort current governed status for a request, else None."""
    approval_id = find_approval_id_by_request(request_id)
    if approval_id is None:
        return None
    try:
        pending = _get_store().get(approval_id)
    except Exception:
        return None
    return pending.status.value