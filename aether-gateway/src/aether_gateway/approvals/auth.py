"""Trusted operator authentication at communication boundaries."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass


class OperatorAuthError(PermissionError):
    pass


@dataclass(frozen=True)
class TrustedOperator:
    principal: str
    channel: str


class OperatorAuthenticator:
    """Constant-time bearer token validation for AionUi/HTTP approval writes."""

    def __init__(self, token: str | None = None, principal: str | None = None) -> None:
        self.token = (token if token is not None else os.environ.get("AETHER_OPERATOR_TOKEN", "")).strip()
        self.principal = (principal if principal is not None else os.environ.get("AETHER_OPERATOR_ID", "founder")).strip()

    @property
    def configured(self) -> bool:
        return bool(self.token and self.principal)

    def authenticate(self, supplied_token: str | None, *, channel: str = "http") -> TrustedOperator:
        if not self.configured:
            raise OperatorAuthError("Trusted operator token is not configured")
        candidate = (supplied_token or "").strip()
        if not candidate or not hmac.compare_digest(candidate, self.token):
            raise OperatorAuthError("Invalid trusted operator token")
        return TrustedOperator(self.principal, channel)
