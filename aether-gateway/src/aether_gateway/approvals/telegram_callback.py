"""Signed Telegram callback payloads for one-tap approval decisions."""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac


@dataclass(frozen=True)
class TelegramApprovalCallback:
    decision: str
    approval_id: str


class TelegramApprovalCallbackCodec:
    """Encode compact callbacks cryptographically bound to one exact action."""

    prefix = "a1"
    _allowed = {"approve", "reject", "details"}
    _wire = {"approve": "a", "reject": "r", "details": "d"}
    _from_wire = {value: key for key, value in _wire.items()}

    def __init__(self, secret: str | bytes) -> None:
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(raw) < 16:
            raise ValueError("Telegram approval callback secret must be at least 16 bytes")
        self._secret = raw

    @staticmethod
    def _action_hash(value: str) -> str:
        normalized = str(value).strip()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("invalid exact action hash")
        return normalized

    def _signature(self, decision_wire: str, approval_id: str, action_hash: str) -> str:
        exact_hash = self._action_hash(action_hash)
        message = f"{self.prefix}|{decision_wire}|{approval_id}|{exact_hash}".encode("utf-8")
        digest = hmac.new(self._secret, message, hashlib.sha256).digest()[:9]
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def encode(self, decision: str, approval_id: str, action_hash: str) -> str:
        if decision not in self._allowed:
            raise ValueError(f"unsupported approval callback decision: {decision}")
        approval_id = str(approval_id).strip()
        if not approval_id.startswith("approval."):
            raise ValueError("invalid approval ID")
        wire = self._wire[decision]
        payload = (
            f"{self.prefix}|{wire}|{approval_id}|"
            f"{self._signature(wire, approval_id, action_hash)}"
        )
        if len(payload.encode("utf-8")) > 64:
            raise ValueError("Telegram callback payload exceeds 64 bytes")
        return payload

    def _parts(self, payload: str) -> tuple[str, str, str]:
        parts = str(payload).split("|")
        if len(parts) != 4 or parts[0] != self.prefix:
            raise ValueError("unsupported Telegram approval callback")
        _, wire, approval_id, signature = parts
        if wire not in self._from_wire or not approval_id.startswith("approval."):
            raise ValueError("invalid Telegram approval callback")
        return wire, approval_id, signature

    def peek_approval_id(self, payload: str) -> str:
        """Extract only the lookup ID; this does not authenticate the callback."""
        _, approval_id, _ = self._parts(payload)
        return approval_id

    def decode(self, payload: str, action_hash: str) -> TelegramApprovalCallback:
        wire, approval_id, signature = self._parts(payload)
        expected = self._signature(wire, approval_id, action_hash)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Telegram approval callback signature mismatch")
        return TelegramApprovalCallback(self._from_wire[wire], approval_id)
