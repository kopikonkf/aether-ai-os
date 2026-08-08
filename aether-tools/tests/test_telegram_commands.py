"""Telegram adapter tests: commands and canonical Sense Event Path routing."""
from __future__ import annotations

import asyncio
import sys
import types
import unittest.mock
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / "aether-gateway" / "src"))
sys.path.insert(0, str(BASE / "aether-core" / "src"))

# Minimal import-safe telegram shim for environments without the optional client.
telegram_mock = types.ModuleType("telegram")
telegram_mock.Update = unittest.mock.MagicMock()
telegram_mock.BotCommand = unittest.mock.MagicMock()
telegram_mock.InlineKeyboardButton = unittest.mock.MagicMock()
telegram_mock.InlineKeyboardMarkup = unittest.mock.MagicMock()
telegram_mock.ext = types.ModuleType("telegram.ext")
telegram_mock.ext.Application = unittest.mock.MagicMock()
telegram_mock.ext.CallbackQueryHandler = unittest.mock.MagicMock()
telegram_mock.ext.CommandHandler = unittest.mock.MagicMock()
telegram_mock.ext.MessageHandler = unittest.mock.MagicMock()
telegram_mock.ext.filters = unittest.mock.MagicMock()
telegram_mock.ext.ContextTypes = unittest.mock.MagicMock()
telegram_mock.ext.ContextTypes.DEFAULT_TYPE = unittest.mock.MagicMock()
sys.modules.setdefault("telegram", telegram_mock)
sys.modules.setdefault("telegram.ext", telegram_mock.ext)
sys.modules.setdefault("telegram.ext.filters", telegram_mock.ext.filters)

from aether.contracts import Expression, Perception
from aether.events import EventBus
from aether.senses import SenseEventPath
from aether_gateway.adapters.telegram_bot import TelegramSenseAdapter
from aether_gateway.approvals import ApprovalInboxService


class CapturingCognition:
    adapter_id = "cognition.capture"

    def __init__(self) -> None:
        self.perceptions: list[Perception] = []

    async def respond(self, perception: Perception) -> Expression:
        self.perceptions.append(perception)
        return Expression(
            modality="text",
            content=f"reply:{perception.content}",
            target=perception.source,
            metadata={"chat_id": perception.metadata["chat_id"]},
        )


class MockUpdate:
    def __init__(self, chat_id: int = 12345, user_id: int = 42, text: str = "") -> None:
        self.message = unittest.mock.MagicMock()
        self.message.chat_id = chat_id
        self.message.text = text
        self.message.message_id = 7
        self.message.reply_text = unittest.mock.AsyncMock()
        self.effective_chat = unittest.mock.MagicMock()
        self.effective_chat.id = chat_id
        self.effective_user = unittest.mock.MagicMock()
        self.effective_user.id = user_id
        self.effective_user.language_code = "id"
        self.effective_message = self.message


class MockContext:
    def __init__(self, args=None) -> None:
        self.args = args or []
        self.bot = unittest.mock.MagicMock()


def build_adapter(
    tmp_path: Path,
    reset=None,
    *,
    approval_coordinator=None,
    approval_inbox=None,
):
    cognition = CapturingCognition()
    sent: list[tuple[int, str]] = []

    async def sender(chat_id: int, text: str) -> None:
        sent.append((chat_id, text))

    path = SenseEventPath(EventBus(tmp_path / "telegram-events.jsonl"), cognition)
    adapter = TelegramSenseAdapter(
        path,
        text_sender=sender,
        session_reset=reset,
        approval_coordinator=approval_coordinator,
        approval_inbox=approval_inbox,
        enabled=False,
    )
    return adapter, cognition, sent, path


def test_start_command_reports_unified_path(tmp_path: Path) -> None:
    adapter, _, _, _ = build_adapter(tmp_path)
    update = MockUpdate()
    asyncio.run(adapter.start_command(update, MockContext()))
    text = update.message.reply_text.call_args[0][0]
    assert "Sense Event Path" in text


def test_clear_command_resets_cognitive_session(tmp_path: Path) -> None:
    reset_sessions: list[str] = []

    async def reset(session_id: str) -> None:
        reset_sessions.append(session_id)

    adapter, _, _, _ = build_adapter(tmp_path, reset=reset)
    update = MockUpdate(chat_id=99)
    asyncio.run(adapter.clear_command(update, MockContext()))
    assert reset_sessions == ["telegram:99"]
    assert "dibersihkan" in update.message.reply_text.call_args[0][0]


def test_model_preference_flows_as_perception_metadata(tmp_path: Path) -> None:
    adapter, cognition, sent, path = build_adapter(tmp_path)
    adapter.model_preferences[12345] = "vendor/model"

    asyncio.run(adapter.ingest_text("hello", chat_id=12345, user_id=42, language="id"))

    assert cognition.perceptions[0].metadata["preferred_model"] == "vendor/model"
    assert cognition.perceptions[0].metadata["session_id"] == "telegram:12345"
    assert sent == [(12345, "reply:hello")]
    assert [event.event_type for event in path.event_bus.replay()] == [
        "perception.received",
        "cognition.requested",
        "cognition.completed",
        "expression.requested",
        "expression.delivered",
    ]


def test_text_update_uses_same_sense_path(tmp_path: Path) -> None:
    adapter, cognition, sent, _ = build_adapter(tmp_path)
    update = MockUpdate(chat_id=7, user_id=8, text="Halo")

    asyncio.run(adapter.handle_text_update(update, MockContext()))

    assert cognition.perceptions[0].modality == "telegram.text"
    assert cognition.perceptions[0].metadata["user_id"] == 8
    assert sent == [(7, "reply:Halo")]


def test_voice_transcript_uses_same_sense_path(tmp_path: Path) -> None:
    adapter, cognition, sent, _ = build_adapter(tmp_path)

    asyncio.run(
        adapter.ingest_voice_transcript(
            "suara",
            chat_id=3,
            user_id=4,
            respond_with_voice=False,
        )
    )

    assert cognition.perceptions[0].modality == "telegram.voice.transcript"
    assert sent == [(3, "reply:suara")]


def test_access_control_blocks_unlisted_user(tmp_path: Path) -> None:
    adapter, cognition, sent, _ = build_adapter(tmp_path)
    adapter.allowed_user_ids = {1}
    update = MockUpdate(user_id=999, text="blocked")

    asyncio.run(adapter.handle_text_update(update, MockContext()))

    assert cognition.perceptions == []
    assert sent == []


def test_model_command_validates_route_format(tmp_path: Path) -> None:
    adapter, _, _, _ = build_adapter(tmp_path)
    update = MockUpdate(chat_id=5)

    asyncio.run(adapter.model_command(update, MockContext(args=["bad-route"])))
    assert "provider/model" in update.message.reply_text.call_args[0][0]

    update.message.reply_text.reset_mock()
    asyncio.run(adapter.model_command(update, MockContext(args=["vendor/model"])))
    assert adapter.model_preferences[5] == "vendor/model"


def test_status_reports_durable_event_count(tmp_path: Path) -> None:
    adapter, _, _, _ = build_adapter(tmp_path)
    update = MockUpdate()
    asyncio.run(adapter.status_command(update, MockContext()))
    assert "Durable events" in update.message.reply_text.call_args[0][0]


def _pending_approval_record(status="pending"):
    from aether.contracts import (
        ActionProposal, ActionResult, ActionRisk, ActionScope, ActionTarget,
        ApprovalOutcome, ApprovalStatus, PendingAction,
    )
    from aether_gateway.approvals import ApprovalResumeOutcome

    proposal = ActionProposal(
        ActionTarget.TOOL,
        "write",
        {"path": "x.txt", "_body": "x"},
        (ActionScope.WRITE,),
        "Write bounded artifact",
        ActionRisk.MEDIUM,
        False,
        metadata={"channel": "telegram", "chat_id": 12345},
        action_id="act.telegram-test",
    )
    result = ActionResult(proposal.action_id, True, "completed", output="written") if status == "consumed" else None
    pending = PendingAction(
        approval_id="approval.telegram-test",
        action_id=proposal.action_id,
        action_hash="a" * 64,
        status=ApprovalStatus(status),
        proposal=proposal,
        requested_at="2026-07-28T00:00:00Z",
        expires_at="2026-07-28T01:00:00Z",
        result=result,
    )
    return pending, ApprovalResumeOutcome(ApprovalOutcome(pending, result))


class FakeApprovalInbox:
    def __init__(self, pending):
        self.pending = pending

    def get(self, approval_id):
        if approval_id != self.pending.approval_id:
            raise KeyError(approval_id)
        return self.pending

    def list(self, _status=None):
        return [self.pending]

    def sweep_expired(self):
        return []


class FakeApprovalCoordinator:
    def __init__(self, pending, outcome):
        self.inbox = FakeApprovalInbox(pending)
        self.outcome = outcome
        self.calls = []

    async def decide(self, approval_id, **kwargs):
        self.calls.append((approval_id, kwargs))
        return self.outcome


def _build_approval_adapter(tmp_path: Path, coordinator: FakeApprovalCoordinator):
    approval_inbox = ApprovalInboxService(coordinator)
    return build_adapter(
        tmp_path,
        approval_coordinator=coordinator,
        approval_inbox=approval_inbox,
    )


def test_approval_commands_require_explicit_operator_allowlist(tmp_path: Path) -> None:
    pending, outcome = _pending_approval_record("consumed")
    coordinator = FakeApprovalCoordinator(pending, outcome)
    adapter, _, _, _ = _build_approval_adapter(tmp_path, coordinator)
    adapter.allowed_user_ids = set()
    update = MockUpdate(user_id=42)

    asyncio.run(adapter.approve_command(update, MockContext(args=[pending.approval_id, "reviewed"])))

    assert coordinator.calls == []
    assert "explicit Telegram operator allowlist" in update.message.reply_text.call_args[0][0]


def test_allowlisted_telegram_operator_can_list_and_decide(tmp_path: Path) -> None:
    pending, outcome = _pending_approval_record("consumed")
    coordinator = FakeApprovalCoordinator(pending, outcome)
    adapter, _, _, _ = _build_approval_adapter(tmp_path, coordinator)
    adapter.allowed_user_ids = {42}
    update = MockUpdate(user_id=42)

    asyncio.run(adapter.approvals_command(update, MockContext()))
    assert pending.approval_id in update.message.reply_text.call_args[0][0]

    update.message.reply_text.reset_mock()
    asyncio.run(adapter.approve_command(update, MockContext(args=[pending.approval_id, "exact", "payload", "reviewed"])))
    assert coordinator.calls[0][0] == pending.approval_id
    assert coordinator.calls[0][1]["principal"] == "telegram:42"
    assert coordinator.calls[0][1]["channel"] == "telegram"
