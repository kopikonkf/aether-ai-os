from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from aether.contracts import ApprovalStatus
from aether_gateway.approvals import ApprovalInboxService


class FakeInbox:
    def __init__(self, rows):
        self.rows = list(rows)
        self.sweeps = 0

    def sweep_expired(self):
        self.sweeps += 1
        return []

    def list(self, status=None):
        if status is None:
            return list(self.rows)
        normalized = ApprovalStatus(str(status))
        return [row for row in self.rows if row.status == normalized]

    def get(self, approval_id):
        return next(row for row in self.rows if row.approval_id == approval_id)


class FakeCoordinator:
    def __init__(self, rows):
        self.inbox = FakeInbox(rows)
        self.calls = []

    async def decide(self, approval_id, **kwargs):
        self.calls.append((approval_id, kwargs))
        return SimpleNamespace(approval_id=approval_id)


def _pending(approval_id="approval.one", *, chat_id=99, action_hash="a" * 64):
    return SimpleNamespace(
        approval_id=approval_id,
        action_hash=action_hash,
        status=ApprovalStatus.PENDING,
        proposal=SimpleNamespace(metadata={"chat_id": chat_id}),
    )


def test_list_and_context_filter_share_one_expiry_sweep() -> None:
    coordinator = FakeCoordinator([_pending(), _pending("approval.two", chat_id=100)])
    service = ApprovalInboxService(coordinator)

    rows = service.list_for_context(metadata_key="chat_id", metadata_value=99)

    assert [row.approval_id for row in rows] == ["approval.one"]
    assert coordinator.inbox.sweeps == 1


def test_decision_can_bind_to_action_hash_seen_by_operator() -> None:
    coordinator = FakeCoordinator([_pending()])
    service = ApprovalInboxService(coordinator)

    asyncio.run(service.decide(
        "approval.one",
        approved=True,
        principal="founder",
        reason="approved",
        channel="http",
        expected_action_hash="a" * 64,
    ))

    assert coordinator.calls[0][0] == "approval.one"

    with pytest.raises(ValueError, match="action hash"):
        asyncio.run(service.decide(
            "approval.one",
            approved=True,
            principal="founder",
            reason="approved",
            channel="http",
            expected_action_hash="b" * 64,
        ))
