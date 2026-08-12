"""Audit trail for Aether MCP OAuth Edge.

Writes append-only JSONL to AETHER_HOME/runtime/oauth-edge/audit.jsonl.
Events: token_issued, token_refreshed, token_revoked, auth_approved,
        auth_rejected, mcp_proxy, scope_denied.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def _audit_path() -> Path:
    aether_home = os.getenv("AETHER_HOME", r"C:\ProgramData\Aether")
    p = Path(aether_home) / "runtime" / "oauth-edge" / "audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _write(event_type: str, data: dict[str, Any]) -> None:
    record = {
        "ts": time.time(),
        "event": event_type,
        **data,
    }
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(_audit_path(), "a", encoding="utf-8") as f:
        f.write(line)


def log_auth_requested(request_id: str, principal_id: str, scopes: list[str]) -> None:
    _write("auth_requested", {
        "request_id": request_id,
        "principal_id": principal_id,
        "scopes": scopes,
    })


def log_auth_approved(request_id: str, principal_id: str, approving_principal: Optional[str] = None) -> None:
    _write("auth_approved", {
        "request_id": request_id,
        "principal_id": principal_id,
        "approving_principal": approving_principal,
    })


def log_auth_rejected(request_id: str, principal_id: str, approving_principal: Optional[str] = None) -> None:
    _write("auth_rejected", {
        "request_id": request_id,
        "principal_id": principal_id,
        "approving_principal": approving_principal,
    })


def log_token_issued(principal_id: str, scopes: list[str], ttl: int) -> None:
    _write("token_issued", {
        "principal_id": principal_id,
        "scopes": scopes,
        "ttl": ttl,
    })


def log_token_refreshed(principal_id: str, scopes: list[str]) -> None:
    _write("token_refreshed", {
        "principal_id": principal_id,
        "scopes": scopes,
    })


def log_token_revoked(principal_id: str, reason: str) -> None:
    _write("token_revoked", {
        "principal_id": principal_id,
        "reason": reason,
    })


def log_mcp_proxy(principal_id: str, scopes: list[str], method: str, path: str, status: int) -> None:
    _write("mcp_proxy", {
        "principal_id": principal_id,
        "scopes": scopes,
        "method": method,
        "path": path,
        "upstream_status": status,
    })


def log_scope_denied(principal_id: str, requested_scope: str) -> None:
    _write("scope_denied", {
        "principal_id": principal_id,
        "requested_scope": requested_scope,
    })
