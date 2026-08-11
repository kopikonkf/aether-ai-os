"""Telegram one-tap approval for browser-sense pairing requests.

Senses pairing requests are created by the browser (BROWSER_SENSE_BOOTSTRAP_REQUESTED)
and currently require an HTTP operator call to approve. This bridge surfaces the
same decision as a Telegram inline keyboard so the founder can approve or reject a
device pairing from the phone, without touching the API.

Callback payloads use their own prefix (``p1``) and are cryptographically bound to
the pairing confirmation code, mirroring the existing approval callback codec.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramPairingCallback:
    decision: str
    bootstrap_id: str


class TelegramPairingCallbackCodec:
    """Encode compact pairing callbacks bound to one exact pairing request."""

    prefix = "p1"
    _allowed = {"approve", "reject"}
    _wire = {"approve": "a", "reject": "r"}
    _from_wire = {value: key for key, value in _wire.items()}

    def __init__(self, secret: str | bytes) -> None:
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(raw) < 16:
            raise ValueError(
                "Telegram pairing callback secret must be at least 16 bytes"
            )
        self._secret = raw

    def _signature(
        self, decision_wire: str, bootstrap_id: str, confirmation_code: str
    ) -> str:
        message = (
            f"{self.prefix}|{decision_wire}|{bootstrap_id}|{confirmation_code}"
        ).encode("utf-8")
        digest = hmac.new(self._secret, message, hashlib.sha256).digest()[:9]
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def encode(
        self, decision: str, bootstrap_id: str, confirmation_code: str
    ) -> str:
        if decision not in self._allowed:
            raise ValueError(
                f"unsupported Telegram pairing callback decision: {decision}"
            )
        bootstrap_id = str(bootstrap_id).strip()
        if not bootstrap_id.startswith("sense-bootstrap"):
            raise ValueError("invalid bootstrap ID")
        wire = self._wire[decision]
        payload = (
            f"{self.prefix}|{wire}|{bootstrap_id}|"
            f"{self._signature(wire, bootstrap_id, confirmation_code)}"
        )
        if len(payload.encode("utf-8")) > 96:
            raise ValueError("Telegram pairing callback payload exceeds 96 bytes")
        return payload

    def _parts(self, payload: str) -> tuple[str, str, str]:
        parts = str(payload).split("|")
        if len(parts) != 4 or parts[0] != self.prefix:
            raise ValueError("unsupported Telegram pairing callback")
        _, wire, bootstrap_id, signature = parts
        if wire not in self._from_wire or not bootstrap_id.startswith(
            "sense-bootstrap"
        ):
            raise ValueError("invalid Telegram pairing callback")
        return wire, bootstrap_id, signature

    def peek_bootstrap_id(self, payload: str) -> str:
        """Extract only the lookup ID; this does not authenticate the callback."""
        _, bootstrap_id, _ = self._parts(payload)
        return bootstrap_id

    def decode(
        self, payload: str, confirmation_code: str
    ) -> TelegramPairingCallback:
        wire, bootstrap_id, signature = self._parts(payload)
        expected = self._signature(wire, bootstrap_id, confirmation_code)
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Telegram pairing callback signature mismatch")
        return TelegramPairingCallback(self._from_wire[wire], bootstrap_id)


class BrowserSensePairingTelegramBridge:
    """Forward browser-sense pairing requests to Telegram with one-tap controls."""

    def __init__(
        self,
        browser_sense_bootstrap: Any,
        *,
        secret: str | bytes,
        allowed_chat_ids: list[int],
        codec: TelegramPairingCallbackCodec | None = None,
    ) -> None:
        self.bootstrap = browser_sense_bootstrap
        self._secret = secret
        self._allowed_chat_ids = list(allowed_chat_ids)
        self._codec = codec or TelegramPairingCallbackCodec(secret)
        self._event_bus = None
        self._bot = None
        self._update_edit = None
        self._send_message: Callable | None = None
        self._edit_message_text: Callable | None = None

    def start(
        self,
        event_bus: Any,
        *,
        bot: Any,
        send_message: Callable[[int, str, Any], Any],
        edit_message_text: Callable[[int, int, str], Any],
    ) -> None:
        """Wire the bridge to the browser-sense event bus and Telegram bot."""
        self._event_bus = event_bus
        self._bot = bot
        self._send_message = send_message
        self._edit_message_text = edit_message_text
        try:
            from aether.contracts import EventType

            self._requested_type = EventType.BROWSER_SENSE_BOOTSTRAP_REQUESTED
        except Exception:  # pragma: no cover - fallback string
            self._requested_type = "browser-sense.bootstrap.requested"
        event_bus.subscribe(self._requested_type, self._on_pairing_requested)

    def _on_pairing_requested(self, event: Any) -> None:
        payload = dict(getattr(event, "payload", {}) or {})
        bootstrap_id = str(payload.get("bootstrap_id") or "")
        device_label = str(payload.get("device_label") or "device")
        mode = str(payload.get("client_mode") or "browser")
        capabilities = payload.get("capabilities") or []
        expires_at = str(payload.get("expires_at") or "?")
        source_hint = str(payload.get("source_hint") or "?")
        if not bootstrap_id or self._bot is None or self._send_message is None:
            return
        try:
            row = self._confirmation_code(bootstrap_id)
        except Exception as exc:
            log.warning(
                "Pairing approval lookup failed for %s: %s", bootstrap_id, exc
            )
            return
        if row is None:
            return
        confirmation_code = str(row.get("confirmation_code") or "")
        if not confirmation_code:
            return
        text = (
            "Aether Senses - Device Pairing Request\n\n"
            f"Device : {device_label}\n"
            f"Mode   : {mode}\n"
            f"Capabilities : {', '.join(capabilities) or '-'}\n"
            f"Source : {source_hint}\n"
            f"Code   : {confirmation_code}\n"
            f"Expires: {expires_at}\n\n"
            "Approve atau Reject pairing device ini?"
        )
        for chat_id in self._allowed_chat_ids:
            try:
                coro = self._send_message(
                    chat_id, text, self._keyboard(bootstrap_id, confirmation_code)
                )
                asyncio.ensure_future(self._safe_send(coro, chat_id))
            except Exception as exc:  # pragma: no cover - delivery best-effort
                log.warning("Pairing approval delivery failed: %s", exc)

    async def _safe_send(self, coro: Any, chat_id: int) -> None:
        try:
            await coro
        except Exception as exc:  # pragma: no cover - delivery best-effort
            log.warning("Pairing approval delivery to %s failed: %s", chat_id, exc)

    def _confirmation_code(self, bootstrap_id: str) -> dict[str, Any] | None:
        try:
            return self.bootstrap._request_public(
                self.bootstrap._request_row(bootstrap_id), state="pending"
            )
        except Exception:
            return None

    def _keyboard(
        self, bootstrap_id: str, confirmation_code: str
    ) -> Any | None:
        try:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        except ImportError:
            return None
        approve = self._codec.encode("approve", bootstrap_id, confirmation_code)
        reject = self._codec.encode("reject", bootstrap_id, confirmation_code)
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Approve", callback_data=approve
                    ),
                    InlineKeyboardButton(
                        "Reject", callback_data=reject
                    ),
                ]
            ]
        )

    async def handle_callback(self, update: Any, context: Any) -> None:
        """Handle Telegram inline callback for a pairing decision."""
        if self._bot is None or self._edit_message_text is None:
            return
        query = update.callback_query
        payload = str(query.data or "")
        if not payload.startswith(self._codec.prefix + "|"):
            return
        bootstrap_id = self._codec.peek_bootstrap_id(payload)
        row = self._confirmation_code(bootstrap_id)
        if row is None:
            await query.answer("Pairing request tidak ditemukan.", show_alert=True)
            return
        confirmation_code = str(row.get("confirmation_code") or "")
        try:
            callback = self._codec.decode(payload, confirmation_code)
        except ValueError:
            await query.answer(
                "Invalid or expired pairing control.", show_alert=True
            )
            return
        approved = callback.decision == "approve"
        await query.answer("Executing." if approved else "Rejected")
        try:
            result = self.bootstrap.decide(
                bootstrap_id,
                approved=approved,
                principal="founder",
                reason="telegram-inline",
                channel="telegram-pairing",
            )
        except Exception as exc:
            await query.edit_message_text(
                text=f"Pairing decision gagal: {type(exc).__name__}: {exc}"
            )
            return
        replayed = bool(result.get("replayed"))
        state = str(result.get("state") or ("approved" if approved else "denied"))
        suffix = " (sudah diproses sebelumnya)" if replayed else ""
        await self._edit_message_text(
            query.message.chat_id,
            query.message.message_id,
            f"Pairing {state}{suffix}",
        )
