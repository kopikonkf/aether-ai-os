from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aether.contracts import ActionResult
from aether_gateway.adapters.telegram_bot import TelegramSenseAdapter
from aether_gateway.approvals import TelegramApprovalCallbackCodec


class FakeInbox:
    def __init__(self, pending) -> None:
        self.pending = pending

    def get(self, approval_id: str):
        if approval_id != self.pending.approval_id:
            raise KeyError(approval_id)
        return self.pending

    def list(self):
        return [self.pending]


class FakeCoordinator:
    def __init__(self, pending, *, replayed: bool = False) -> None:
        self.inbox = FakeInbox(pending)
        self.replayed = replayed
        self.calls: list[dict] = []

    async def decide(self, approval_id, *, approved, principal, reason, channel):
        self.calls.append({
            "approval_id": approval_id,
            "approved": approved,
            "principal": principal,
            "reason": reason,
            "channel": channel,
        })
        result = ActionResult(
            self.inbox.pending.action_id,
            approved,
            "completed" if approved else "rejected",
            metadata={"data": {"path": "workspace/proof.md"}},
        )
        approval = SimpleNamespace(
            pending=self.inbox.pending,
            replayed=self.replayed,
            result=result,
        )
        expression = (
            SimpleNamespace(
                content="authoritative completed receipt",
                modality="text",
                metadata={"chat_id": 99},
                target="telegram:99",
            )
            if approved and not self.replayed
            else None
        )
        return SimpleNamespace(approval=approval, expression=expression)


class FakeMessage:
    def __init__(self, chat_id: int = 99) -> None:
        self.chat = SimpleNamespace(id=chat_id)
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeQuery:
    def __init__(self, data: str, *, user_id: int = 7, chat_id: int = 99) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage(chat_id)
        self.answers: list[tuple[str | None, bool]] = []
        self.edits: list[str] = []

    async def answer(self, text=None, show_alert=False) -> None:
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text: str) -> None:
        self.edits.append(text)


def _pending(chat_id: int = 99):
    return SimpleNamespace(
        approval_id="approval.1234567890abcdef",
        action_id="act.1234567890abcdef",
        action_hash="a" * 64,
        expires_at="2026-07-29T12:00:00Z",
        proposal=SimpleNamespace(
            metadata={"chat_id": chat_id},
            target=SimpleNamespace(value="tool"),
            operation="write",
            risk=SimpleNamespace(value="medium"),
            reversible=False,
            arguments={"path": "workspace/proof.md"},
            reason="Founder requested a proof file",
            required_scopes=(),
        ),
    )


def _adapter(pending, codec):
    coordinator = FakeCoordinator(pending)
    adapter = TelegramSenseAdapter(
        SimpleNamespace(),
        approval_coordinator=coordinator,
        approval_callback_codec=codec,
        enabled=False,
    )
    adapter.allowed_user_ids = {7}
    return adapter, coordinator


def test_callback_codec_is_compact_restart_safe_and_tamper_evident() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    payload = codec.encode("approve", "approval.1234567890abcdef")
    assert len(payload.encode("utf-8")) <= 64
    decoded = codec.decode(payload)
    assert decoded.decision == "approve"
    assert decoded.approval_id == "approval.1234567890abcdef"

    with pytest.raises(ValueError, match="signature"):
        codec.decode(payload[:-1] + ("A" if payload[-1] != "A" else "B"))


def test_inline_approve_is_bound_to_founder_and_chat_and_edits_original_card() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    adapter, coordinator = _adapter(pending, codec)
    query = FakeQuery(codec.encode("approve", pending.approval_id))
    update = SimpleNamespace(callback_query=query)

    asyncio.run(adapter.approval_callback(update, SimpleNamespace()))

    assert coordinator.calls == [{
        "approval_id": pending.approval_id,
        "approved": True,
        "principal": "telegram:7",
        "reason": "Founder approved once via Telegram inline control",
        "channel": "telegram-inline",
    }]
    # Fresh approval with a follow-up Expression: the card collapses to a short
    # final status. This adapter has no transport, so follow-up delivery fails
    # and the card must say the action finished but delivery failed.
    assert query.edits == [
        "✅ Action selesai, tapi balasan lanjutan gagal terkirim: RuntimeError"
    ]


def test_inline_callback_rejects_wrong_chat_without_consuming_approval() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending(chat_id=99)
    adapter, coordinator = _adapter(pending, codec)
    query = FakeQuery(codec.encode("approve", pending.approval_id), chat_id=100)

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert coordinator.calls == []
    assert query.answers[-1][1] is True
    assert "different chat" in (query.answers[-1][0] or "")


def test_details_callback_does_not_consume_approval() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    adapter, coordinator = _adapter(pending, codec)
    query = FakeQuery(codec.encode("details", pending.approval_id))

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert coordinator.calls == []
    assert query.message.replies
    assert pending.approval_id in query.message.replies[-1]


def _adapter_with_sender(pending, codec, sender, *, replayed=False):
    coordinator = FakeCoordinator(pending, replayed=replayed)
    adapter = TelegramSenseAdapter(
        SimpleNamespace(),
        approval_coordinator=coordinator,
        approval_callback_codec=codec,
        text_sender=sender,
        enabled=False,
    )
    adapter.allowed_user_ids = {7}
    return adapter, coordinator


def test_fresh_approval_sends_exactly_one_followup_message() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    sent: list[tuple[int, str]] = []
    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))
    adapter, _ = _adapter_with_sender(pending, codec, sender)
    query = FakeQuery(codec.encode("approve", pending.approval_id))

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert sent == [(99, "authoritative completed receipt")]
    assert query.edits == ["✅ Approved — balasan lanjutan dikirim."]


def test_delivery_failure_does_not_claim_sent() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    sent: list[tuple[int, str]] = []
    async def failing_sender(chat_id: int, text: str) -> None:
        raise RuntimeError("telegram transport down")
    adapter, _ = _adapter_with_sender(pending, codec, failing_sender)
    query = FakeQuery(codec.encode("approve", pending.approval_id))

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert sent == []
    assert query.edits == [
        "✅ Action selesai, tapi balasan lanjutan gagal terkirim: RuntimeError"
    ]
    assert "lanjutan dikirim" not in query.edits[0]


def test_replay_sends_no_followup_message() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    sent: list[tuple[int, str]] = []
    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))
    adapter, _ = _adapter_with_sender(pending, codec, sender, replayed=True)
    query = FakeQuery(codec.encode("approve", pending.approval_id))

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert sent == []
    assert query.edits[0].startswith("Approval approval.1234567890abcdef")


def test_rejection_sends_no_followup_message() -> None:
    codec = TelegramApprovalCallbackCodec("x" * 32)
    pending = _pending()
    sent: list[tuple[int, str]] = []
    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))
    adapter, _ = _adapter_with_sender(pending, codec, sender)
    query = FakeQuery(codec.encode("reject", pending.approval_id))

    asyncio.run(adapter.approval_callback(SimpleNamespace(callback_query=query), SimpleNamespace()))

    assert sent == []
    assert query.edits[0].startswith("Rejected approval.1234567890abcdef")
