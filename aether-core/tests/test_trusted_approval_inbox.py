from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aether.actions import (
    ApprovalIntegrityError,
    FailureFingerprintStore,
    GovernedActionPath,
    PendingActionStore,
    TrustedApprovalInbox,
)
from aether.contracts import (
    ActionCapability,
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    ApprovalStatus,
    RuntimeResult,
    canonical_action_hash,
)
from aether.events import EventBus
from aether.governance import ActionGovernor


class FakeToolExecutor:
    def __init__(self, result: RuntimeResult | None = None):
        self.result = result or RuntimeResult(True, output="written")
        self.calls = 0

    async def capabilities(self):
        return [
            ActionCapability(ActionTarget.TOOL, "write", "write", (ActionScope.WRITE,), False, {"type": "object"})
        ]

    async def execute_tool(self, operation, arguments):
        self.calls += 1
        return self.result


def _proposal() -> ActionProposal:
    return ActionProposal(
        ActionTarget.TOOL,
        "write",
        {"path": "artifact.txt", "content": "verified"},
        (ActionScope.WRITE,),
        "Write one bounded verified artifact",
        ActionRisk.MEDIUM,
        False,
        correlation_id="corr.approval-test",
        metadata={"channel": "http", "session_id": "http:test"},
    )


def _system(tmp_path: Path, *, clock=None, ttl=900):
    backend = FakeToolExecutor()
    bus = EventBus(tmp_path / "actions.jsonl")
    store = PendingActionStore(tmp_path / "pending.sqlite3", clock=clock, default_ttl_seconds=ttl)
    path = GovernedActionPath(
        bus,
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
        pending_store=store,
        approval_ttl_seconds=ttl,
    )
    return backend, bus, store, path, TrustedApprovalInbox(store, path, bus)


def test_approval_required_action_becomes_durable_pending_record(tmp_path: Path) -> None:
    backend, bus, store, path, _ = _system(tmp_path)
    proposal = _proposal()
    result = asyncio.run(path.execute(proposal))
    assert result.status == "pending-approval"
    assert backend.calls == 0
    pending = store.get(str(result.metadata["approval_id"]))
    assert pending.status == ApprovalStatus.PENDING
    assert pending.action_hash == canonical_action_hash(proposal)
    assert pending.proposal == proposal
    assert [event.event_type for event in bus.replay()] == [
        "action.proposed",
        "governance.approval-required",
        "approval.requested",
    ]


def test_approved_action_resumes_exactly_once_and_replay_returns_cached_result(tmp_path: Path) -> None:
    backend, bus, store, path, inbox = _system(tmp_path)
    pending_result = asyncio.run(path.execute(_proposal()))
    approval_id = str(pending_result.metadata["approval_id"])

    first = asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=True,
        principal="founder",
        reason="Reviewed exact path and content",
        channel="http",
    ))
    second = asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=True,
        principal="founder",
        reason="Repeated client request",
        channel="http",
    ))

    assert first.result is not None and first.result.ok
    assert first.pending.status == ApprovalStatus.CONSUMED
    assert second.replayed and second.result == first.result
    assert backend.calls == 1
    records = store.approval_records(approval_id)
    assert len(records) == 1
    assert records[0]["principal"] == "founder"
    assert records[0]["action_hash"] == first.pending.action_hash
    assert "approval.replay-blocked" in [event.event_type for event in bus.replay()]


def test_rejected_action_never_executes(tmp_path: Path) -> None:
    backend, _, store, path, inbox = _system(tmp_path)
    pending_result = asyncio.run(path.execute(_proposal()))
    outcome = asyncio.run(inbox.decide_and_resume(
        str(pending_result.metadata["approval_id"]),
        approved=False,
        principal="founder",
        reason="Requested write is not necessary",
        channel="telegram",
    ))
    assert outcome.pending.status == ApprovalStatus.REJECTED
    assert outcome.result is None
    assert backend.calls == 0
    assert len(store.approval_records(outcome.pending.approval_id)) == 1


def test_expired_approval_cannot_be_revived(tmp_path: Path) -> None:
    now = [datetime(2026, 7, 28, 0, 0, tzinfo=timezone.utc)]
    backend, bus, store, path, inbox = _system(tmp_path, clock=lambda: now[0], ttl=30)
    pending_result = asyncio.run(path.execute(_proposal()))
    approval_id = str(pending_result.metadata["approval_id"])
    now[0] += timedelta(seconds=31)
    expired = inbox.sweep_expired()
    assert [item.approval_id for item in expired] == [approval_id]
    outcome = asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=True,
        principal="founder",
        reason="Too late",
        channel="http",
    ))
    assert outcome.pending.status == ApprovalStatus.EXPIRED
    assert backend.calls == 0
    assert "approval.expired" in [event.event_type for event in bus.replay()]


def test_proposal_tampering_breaks_hash_integrity(tmp_path: Path) -> None:
    _, _, store, path, _ = _system(tmp_path)
    result = asyncio.run(path.execute(_proposal()))
    approval_id = str(result.metadata["approval_id"])
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE pending_actions SET proposal_json = replace(proposal_json, 'artifact.txt', 'other.txt') WHERE approval_id = ?",
            (approval_id,),
        )
    with pytest.raises(ApprovalIntegrityError):
        store.get(approval_id)


def test_approval_decision_rows_are_immutable(tmp_path: Path) -> None:
    _, _, store, path, inbox = _system(tmp_path)
    result = asyncio.run(path.execute(_proposal()))
    approval_id = str(result.metadata["approval_id"])
    asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=False,
        principal="founder",
        reason="No",
        channel="http",
    ))
    record_id = store.approval_records(approval_id)[0]["record_id"]
    with sqlite3.connect(store.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE approval_records SET reason = 'changed' WHERE record_id = ?",
            (record_id,),
        )


def test_reject_cannot_reverse_or_trigger_an_already_consumed_approval(tmp_path: Path) -> None:
    backend, _, _, path, inbox = _system(tmp_path)
    pending_result = asyncio.run(path.execute(_proposal()))
    approval_id = str(pending_result.metadata["approval_id"])
    asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=True,
        principal="founder",
        reason="Approved",
        channel="http",
    ))
    contradictory = asyncio.run(inbox.decide_and_resume(
        approval_id,
        approved=False,
        principal="founder",
        reason="Late reject",
        channel="http",
    ))
    assert contradictory.replayed
    assert contradictory.pending.status == ApprovalStatus.CONSUMED
    assert backend.calls == 1
