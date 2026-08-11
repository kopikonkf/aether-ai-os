from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aether_gateway.adapters.pairing_telegram import (
    BrowserSensePairingTelegramBridge,
    TelegramPairingCallbackCodec,
)

BOOTSTRAP_ID = "sense-bootstrap.test1234567890abcdef"
CODE = "089883"


def test_pairing_callback_codec_is_compact_and_tamper_evident() -> None:
    codec = TelegramPairingCallbackCodec("x" * 32)
    payload = codec.encode("approve", BOOTSTRAP_ID, CODE)
    assert payload.startswith("p1|")
    assert len(payload.encode("utf-8")) <= 96
    decoded = codec.decode(payload, CODE)
    assert decoded.decision == "approve"
    assert decoded.bootstrap_id == BOOTSTRAP_ID

    with pytest.raises(ValueError, match="signature"):
        codec.decode(payload[:-1] + ("A" if payload[-1] != "A" else "B"), CODE)
    with pytest.raises(ValueError, match="signature"):
        codec.decode(payload, "000000")

    peek = codec.peek_bootstrap_id(payload)
    assert peek == BOOTSTRAP_ID


def test_pairing_callback_codec_rejects_bad_ids() -> None:
    codec = TelegramPairingCallbackCodec("x" * 32)
    with pytest.raises(ValueError, match="bootstrap ID"):
        codec.encode("approve", "approval.123", CODE)
    with pytest.raises(ValueError, match="decision"):
        codec.encode("details", BOOTSTRAP_ID, CODE)


class FakeBootstrap:
    def __init__(self) -> None:
        self.decisions: list[dict] = []

    def _request_row(self, bootstrap_id: str):
        if bootstrap_id != BOOTSTRAP_ID:
            raise KeyError(bootstrap_id)
        return {"confirmation_code": CODE}

    def _request_public(self, row, *, state: str):
        return {
            "bootstrap_id": BOOTSTRAP_ID,
            "state": state,
            "confirmation_code": CODE,
            "device_label": "test-device",
            "client_mode": "browser",
            "capabilities": ["text", "camera"],
            "source_hint": "192.168.1.x",
            "expires_at": "2026-08-11T18:00:00Z",
        }

    def decide(self, bootstrap_id, *, approved, principal, reason, channel):
        self.decisions.append({
            "bootstrap_id": bootstrap_id,
            "approved": approved,
            "principal": principal,
            "reason": reason,
            "channel": channel,
        })
        return {
            "bootstrap_id": bootstrap_id,
            "state": "approved" if approved else "denied",
            "replayed": False,
        }


class FakeEventBus:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}
        self.subscribed: list[str] = []

    def subscribe(self, event_type: str, handler) -> None:
        self.subscribed.append(event_type)
        self.handlers.setdefault(event_type, []).append(handler)


class FakeEvent:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


class FakeBot:
    pass


def _make_bridge() -> tuple[BrowserSensePairingTelegramBridge, FakeBootstrap]:
    bootstrap = FakeBootstrap()
    bridge = BrowserSensePairingTelegramBridge(
        bootstrap,
        secret="x" * 32,
        allowed_chat_ids=[6051954942],
    )
    return bridge, bootstrap


def test_bridge_subscribes_to_pairing_requested_event() -> None:
    bridge, _ = _make_bridge()
    bus = FakeEventBus()
    sent: list[dict] = []
    edits: list[dict] = []

    async def send_message(chat_id: int, text: str, markup) -> None:
        sent.append({"chat_id": chat_id, "text": text, "markup": markup})

    async def edit_message_text(chat_id: int, message_id: int, text: str) -> None:
        edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})

    bridge.start(
        bus,
        bot=FakeBot(),
        send_message=send_message,
        edit_message_text=edit_message_text,
    )
    assert bus.subscribed == ["browser-sense.bootstrap.requested"]

    bridge._on_pairing_requested(
        FakeEvent({
            "bootstrap_id": BOOTSTRAP_ID,
            "device_label": "test-device",
            "client_mode": "browser",
            "capabilities": ["text", "camera"],
            "source_hint": "192.168.1.x",
            "expires_at": "2026-08-11T18:00:00Z",
        })
    )
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
    assert len(sent) == 1
    assert sent[0]["chat_id"] == 6051954942
    assert CODE in sent[0]["text"]
    assert "Device : test-device" in sent[0]["text"]
    assert sent[0]["markup"] is not None
    approve_payload = sent[0]["markup"].inline_keyboard[0][0].callback_data
    assert approve_payload.startswith("p1|")
    codec = TelegramPairingCallbackCodec("x" * 32)
    decoded = codec.decode(approve_payload, CODE)
    assert decoded.decision == "approve"
    assert decoded.bootstrap_id == BOOTSTRAP_ID


def test_bridge_callback_approves_pairing_via_bootstrap_decide() -> None:
    bridge, bootstrap = _make_bridge()
    codec = TelegramPairingCallbackCodec("x" * 32)
    payload = codec.encode("approve", BOOTSTRAP_ID, CODE)
    edits: list[dict] = []
    answers: list[tuple] = []

    class Query:
        def __init__(self):
            self.data = payload
            self.message = SimpleNamespace(chat_id=7, message_id=1)

        async def answer(self, text=None, show_alert=False) -> None:
            answers.append((text, show_alert))

        async def edit_message_text(self, text: str) -> None:
            edits.append(text)

    query = Query()

    async def edit_message_text(chat_id: int, message_id: int, text: str) -> None:
        edits.append({"chat_id": chat_id, "message_id": message_id, "text": text})

    bridge._edit_message_text = edit_message_text
    bridge._bot = FakeBot()

    asyncio.run(
        bridge.handle_callback(
            SimpleNamespace(callback_query=query), SimpleNamespace()
        )
    )
    assert bootstrap.decisions == [{
        "bootstrap_id": BOOTSTRAP_ID,
        "approved": True,
        "principal": "founder",
        "reason": "telegram-inline",
        "channel": "telegram-pairing",
    }]
    assert edits[-1] == {"chat_id": 7, "message_id": 1, "text": "Pairing approved"}


def test_bridge_callback_rejects_tampered_signature() -> None:
    bridge, bootstrap = _make_bridge()
    codec = TelegramPairingCallbackCodec("x" * 32)
    payload = codec.encode("reject", BOOTSTRAP_ID, CODE)
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    answers: list[tuple] = []

    class Query:
        def __init__(self):
            self.data = tampered

        async def answer(self, text=None, show_alert=False) -> None:
            answers.append((text, show_alert))

    bridge._bot = FakeBot()
    bridge._edit_message_text = (
        lambda chat_id, message_id, text: None
    )
    asyncio.run(
        bridge.handle_callback(
            SimpleNamespace(callback_query=Query()), SimpleNamespace()
        )
    )
    assert bootstrap.decisions == []
    assert answers[-1][1] is True
    assert "expired" in (answers[-1][0] or "").lower() or "invalid" in (answers[-1][0] or "").lower()
