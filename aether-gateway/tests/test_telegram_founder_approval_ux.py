from __future__ import annotations

import asyncio
from types import SimpleNamespace

from aether.contracts import ActionResult, Expression
from aether_gateway.adapters.telegram_bot import TelegramSenseAdapter


class FakeMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.replies.append(text)


class FakeUpdate:
    def __init__(self, *, user_id: int = 7, chat_id: int = 99) -> None:
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.message = FakeMessage()


class FakeInbox:
    def __init__(self, rows) -> None:
        self.rows = list(rows)

    def list(self):
        return list(self.rows)


class FakeCoordinator:
    def __init__(self, rows, expression: Expression | None = None) -> None:
        self.inbox = FakeInbox(rows)
        self.expression = expression
        self.calls: list[dict] = []

    async def decide(self, approval_id, *, approved, principal, reason, channel):
        self.calls.append({
            "approval_id": approval_id,
            "approved": approved,
            "principal": principal,
            "reason": reason,
            "channel": channel,
        })
        pending = next(row for row in self.inbox.rows if row.approval_id == approval_id)
        approval = SimpleNamespace(
            pending=pending,
            replayed=False,
            result=ActionResult(pending.action_id, True, "completed"),
        )
        return SimpleNamespace(approval=approval, expression=self.expression)


def _pending(approval_id: str, *, chat_id: int = 99):
    return SimpleNamespace(
        approval_id=approval_id,
        action_id=f"act.{approval_id}",
        proposal=SimpleNamespace(metadata={"chat_id": chat_id}),
    )


def _adapter(coordinator, sent: list[str]):
    async def sender(chat_id: int, text: str) -> None:
        sent.append(f"{chat_id}:{text}")

    sense_path = SimpleNamespace()
    adapter = TelegramSenseAdapter(
        sense_path,
        approval_coordinator=coordinator,
        text_sender=sender,
        enabled=False,
    )
    adapter.allowed_user_ids = {7}
    return adapter


def test_yes_approves_only_pending_action_in_same_chat_with_default_reason():
    pending = _pending("approval.one")
    expression = Expression(
        "text",
        "authoritative receipt",
        "telegram:99",
        {"chat_id": 99},
    )
    coordinator = FakeCoordinator([pending], expression)
    sent: list[str] = []
    adapter = _adapter(coordinator, sent)
    update = FakeUpdate()
    context = SimpleNamespace(args=[])

    asyncio.run(adapter.yes_command(update, context))

    assert coordinator.calls == [{
        "approval_id": "approval.one",
        "approved": True,
        "principal": "telegram:7",
        "reason": "Founder approved once via trusted Telegram session",
        "channel": "telegram",
    }]
    assert sent == ["99:authoritative receipt"]
    assert update.message.replies == []


def test_quick_decision_is_rejected_when_multiple_actions_are_pending():
    coordinator = FakeCoordinator([_pending("approval.one"), _pending("approval.two")])
    sent: list[str] = []
    adapter = _adapter(coordinator, sent)
    update = FakeUpdate()

    asyncio.run(adapter.yes_command(update, SimpleNamespace(args=[])))

    assert coordinator.calls == []
    assert "lebih dari satu pending approval" in update.message.replies[-1]


def test_explicit_approval_id_does_not_require_manual_reason_for_founder_telegram():
    pending = _pending("approval.one")
    coordinator = FakeCoordinator([pending])
    sent: list[str] = []
    adapter = _adapter(coordinator, sent)
    update = FakeUpdate()

    asyncio.run(adapter.approve_command(update, SimpleNamespace(args=["approval.one"])))

    assert coordinator.calls[0]["approval_id"] == "approval.one"
    assert coordinator.calls[0]["reason"] == "Founder approved once via trusted Telegram session"
    assert "Status: completed" in update.message.replies[-1]
