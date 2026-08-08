from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aether.actions import FailureFingerprintStore, GovernedActionPath
from aether.actions import ActionControlConflict, ActionControlIntegrityError
from aether.contracts import (
    ActionApproval, ActionCapability, ActionProposal, ActionRisk, ActionScope, ActionTarget,
    RuntimeResult, canonical_action_hash,
)
from aether.events import EventBus
from aether.governance import ActionGovernor


class FakeToolExecutor:
    def __init__(self, result: RuntimeResult):
        self.result = result
        self.calls = 0

    async def capabilities(self):
        return [ActionCapability(ActionTarget.TOOL, "read", "read", (ActionScope.READ,), True, {"type": "object"})]

    async def execute_tool(self, operation, arguments):
        self.calls += 1
        return self.result


class SlowCancellableToolExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.cancel_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def capabilities(self):
        return [ActionCapability(
            ActionTarget.TOOL,
            "read",
            "bounded cancellable read",
            (ActionScope.READ,),
            True,
            {"type": "object"},
            cancel_supported=True,
        )]

    async def execute_tool(self, operation, arguments):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return RuntimeResult(True, output="completed-once")

    async def cancel_tool(self, action_id, operation, arguments):
        self.cancel_calls += 1
        return RuntimeResult(True, output="cancel-acknowledged")


class SlowUnsupportedToolExecutor(SlowCancellableToolExecutor):
    async def capabilities(self):
        return [ActionCapability(
            ActionTarget.TOOL,
            "read",
            "bounded read without cancellation acknowledgement",
            (ActionScope.READ,),
            True,
            {"type": "object"},
            cancel_supported=False,
        )]


class CancellationIgnoringToolExecutor(SlowCancellableToolExecutor):
    async def execute_tool(self, operation, arguments):
        self.calls += 1
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            # Model an upstream adapter that acknowledged cancel but still
            # delivered a late result. The governed path must discard it.
            pass
        return RuntimeResult(True, output="late-sensitive-output")


def _path(tmp_path: Path, backend: FakeToolExecutor) -> GovernedActionPath:
    return GovernedActionPath(
        EventBus(tmp_path / "actions.jsonl"),
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
    )


def test_read_action_is_governed_and_completed(tmp_path: Path) -> None:
    backend = FakeToolExecutor(RuntimeResult(True, output="hello"))
    path = _path(tmp_path, backend)
    proposal = ActionProposal(ActionTarget.TOOL, "read", {"path": "x"}, (ActionScope.READ,), "Read bounded workspace evidence")
    result = asyncio.run(path.execute(proposal))
    assert result.ok and result.output == "hello"
    assert backend.calls == 1
    assert [e.event_type for e in path.event_bus.replay()] == [
        "action.proposed", "governance.approved", "action.execution.requested", "action.completed"
    ]


def test_write_action_requires_trusted_approval(tmp_path: Path) -> None:
    backend = FakeToolExecutor(RuntimeResult(True, output="written"))
    path = _path(tmp_path, backend)
    proposal = ActionProposal(ActionTarget.TOOL, "write", {"path": "x"}, (ActionScope.WRITE,), "Write a governed artifact", ActionRisk.MEDIUM, False)
    denied = asyncio.run(path.execute(proposal))
    assert not denied.ok and denied.status == "approval-required"
    approval = ActionApproval(
        "founder",
        (ActionScope.WRITE,),
        "Founder approved this bounded write",
        action_hash=canonical_action_hash(proposal),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        channel="test",
    )
    allowed = asyncio.run(path.execute(proposal, approval))
    assert allowed.ok


def test_identical_failure_is_blocked_without_explicit_retry_reason(tmp_path: Path) -> None:
    backend = FakeToolExecutor(RuntimeResult(False, error="missing", metadata={"error_type": "NotFound"}))
    path = _path(tmp_path, backend)
    base = ActionProposal(ActionTarget.TOOL, "read", {"path": "missing"}, (ActionScope.READ,), "Read expected evidence")
    first = asyncio.run(path.execute(base))
    second = asyncio.run(path.execute(ActionProposal(ActionTarget.TOOL, "read", {"path": "missing"}, (ActionScope.READ,), "Read expected evidence")))
    third = asyncio.run(path.execute(ActionProposal(ActionTarget.TOOL, "read", {"path": "missing"}, (ActionScope.READ,), "Retry after verifying the path is now mounted", retry_reason="Mount state materially changed")))
    assert first.status == "failed" and first.failure_fingerprint
    assert second.status == "retry-blocked"
    assert third.status == "failed"
    assert backend.calls == 2


class PreflightToolExecutor(FakeToolExecutor):
    def __init__(self, validation: RuntimeResult, execution: RuntimeResult):
        super().__init__(execution)
        self.validation = validation
        self.validation_calls = 0

    async def validate_tool(self, operation, arguments):
        self.validation_calls += 1
        return self.validation


def test_impossible_write_fails_preflight_before_approval(tmp_path: Path) -> None:
    backend = PreflightToolExecutor(
        RuntimeResult(False, error="Write access denied; target is outside configured roots: D:\\\\"),
        RuntimeResult(True, output="must-not-run"),
    )
    store = __import__('aether.actions', fromlist=['PendingActionStore']).PendingActionStore(tmp_path / "pending.sqlite3")
    path = GovernedActionPath(
        EventBus(tmp_path / "actions.jsonl"),
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
        pending_store=store,
    )
    proposal = ActionProposal(
        ActionTarget.TOOL,
        "write",
        {"path": "D:\\\\first.md", "content": "hello"},
        (ActionScope.WRITE,),
        "Write outside AETHER_HOME",
        ActionRisk.MEDIUM,
        False,
    )
    result = asyncio.run(path.execute(proposal))
    assert result.status == "preflight-failed"
    assert "outside configured roots" in (result.error or "")
    assert backend.validation_calls == 1
    assert backend.calls == 0
    assert store.list() == []
    assert [event.event_type for event in path.event_bus.replay()] == [
        "action.proposed", "action.preflight.failed"
    ]


def test_identical_write_failure_is_blocked_before_second_approval(tmp_path: Path) -> None:
    backend = PreflightToolExecutor(
        RuntimeResult(True, output="valid"),
        RuntimeResult(False, error="disk failure", metadata={"error_type": "DiskError"}),
    )
    store = __import__('aether.actions', fromlist=['PendingActionStore']).PendingActionStore(tmp_path / "pending.sqlite3")
    path = GovernedActionPath(
        EventBus(tmp_path / "actions.jsonl"),
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
        pending_store=store,
    )
    proposal = ActionProposal(
        ActionTarget.TOOL, "write", {"path": "workspace/x.md", "content": "x"},
        (ActionScope.WRITE,), "Write artifact", ActionRisk.MEDIUM, False,
    )
    first = asyncio.run(path.execute(proposal))
    approval = ActionApproval(
        "founder", (ActionScope.WRITE,), "approved", action_hash=canonical_action_hash(proposal),
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
    )
    failed = asyncio.run(path.execute(proposal, approval))
    second = asyncio.run(path.execute(ActionProposal(
        ActionTarget.TOOL, "write", {"path": "workspace/x.md", "content": "x"},
        (ActionScope.WRITE,), "Write artifact again", ActionRisk.MEDIUM, False,
    )))
    assert first.status == "pending-approval"
    assert failed.status == "failed"
    assert second.status == "retry-blocked"
    assert len(store.list()) == 1


def test_read_only_discovery_tools_do_not_interrupt_founder_with_approval(tmp_path: Path) -> None:
    for operation, scopes, risk in (
        ("glob", (ActionScope.READ,), ActionRisk.LOW),
        ("grep", (ActionScope.READ,), ActionRisk.LOW),
    ):
        backend = FakeToolExecutor(RuntimeResult(True, output=f"{operation}-ok"))
        path = _path(tmp_path / operation, backend)
        proposal = ActionProposal(
            ActionTarget.TOOL,
            operation,
            {"path": "workspace"},
            scopes,
            f"Use bounded read-only capability {operation}",
            risk,
            True,
        )
        result = asyncio.run(path.execute(proposal))
        assert result.ok
        assert backend.calls == 1
        assert path.event_bus.replay()[1].payload["mode"] == "auto-approved"


def _browser_proposal(action_id: str = "act.browser-control") -> ActionProposal:
    return ActionProposal(
        ActionTarget.TOOL,
        "read",
        {"path": "workspace/proof.md"},
        (ActionScope.READ,),
        "Read bounded proof",
        metadata={"channel": "browser", "session_id": "browser:sense-session.1"},
        action_id=action_id,
    )


def test_supported_cancel_is_exact_bound_single_use_and_terminal(tmp_path: Path) -> None:
    async def scenario() -> None:
        backend = SlowCancellableToolExecutor()
        path = _path(tmp_path, backend)
        proposal = _browser_proposal()
        execution = asyncio.create_task(path.execute(proposal))
        await backend.started.wait()

        outcome = await path.cancel_action(
            proposal.action_id,
            control_request_id="cancel.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            reason="founder-explicit-cancel",
        )
        result = await execution

        assert outcome.status == "canceled"
        assert outcome.terminal is True
        assert result.status == "canceled"
        assert backend.calls == 1
        assert backend.cancel_calls == 1
        assert [event.event_type for event in path.event_bus.replay()] == [
            "action.proposed",
            "governance.approved",
            "action.execution.requested",
            "action.cancel.intent-recorded",
            "action.cancel.requested",
            "action.canceled",
        ]

        replay = await path.cancel_action(
            proposal.action_id,
            control_request_id="cancel.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            reason="founder-explicit-cancel",
        )
        assert replay.replayed is True
        assert backend.cancel_calls == 1
        with pytest.raises(ActionControlConflict):
            await path.cancel_action(
                proposal.action_id,
                control_request_id="cancel.2",
                expected_action_hash=canonical_action_hash(proposal),
                session_id="sense-session.1",
                principal="founder",
                reason="founder-explicit-cancel",
            )

    asyncio.run(scenario())


def test_acknowledged_cancel_discards_late_adapter_result_hash_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        backend = CancellationIgnoringToolExecutor()
        path = _path(tmp_path, backend)
        proposal = _browser_proposal("act.late-after-cancel")
        execution = asyncio.create_task(path.execute(proposal))
        await backend.started.wait()

        await path.cancel_action(
            proposal.action_id,
            control_request_id="cancel.late.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            reason="founder-explicit-cancel",
        )
        result = await execution
        events = path.event_bus.replay()

        assert result.status == "canceled"
        assert not any(event.event_type == "action.completed" for event in events)
        discarded = next(
            event for event in events
            if event.event_type == "action.late-result.discarded"
        )
        assert len(discarded.payload["result_hash"]) == 64
        assert "late-sensitive-output" not in str(discarded.payload)

    asyncio.run(scenario())


def test_network_ambiguous_waiter_reconciles_without_cancel_or_resubmission(tmp_path: Path) -> None:
    async def scenario() -> None:
        backend = SlowCancellableToolExecutor()
        path = _path(tmp_path, backend)
        proposal = _browser_proposal("act.ambiguous")
        waiter = asyncio.create_task(path.execute(proposal))
        await backend.started.wait()

        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        receipt = await path.reconcile_action(
            proposal.action_id,
            control_request_id="reconcile.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            observed_receipt_id=next(
                event.event_id
                for event in path.event_bus.replay()
                if event.event_type == "action.execution.requested"
            ),
        )
        assert receipt.status == "not-confirmed"
        assert receipt.terminal is False
        assert backend.calls == 1
        assert backend.cancel_calls == 0

        backend.release.set()
        for _ in range(20):
            if any(event.event_type == "action.completed" for event in path.event_bus.replay()):
                break
            await asyncio.sleep(0)
        assert backend.calls == 1
        assert [event.event_type for event in path.event_bus.replay()].count(
            "action.execution.requested"
        ) == 1
        assert [event.event_type for event in path.event_bus.replay()].count(
            "action.reconciliation.requested"
        ) == 1
        assert any(event.event_type == "action.completed" for event in path.event_bus.replay())

        replay = await path.reconcile_action(
            proposal.action_id,
            control_request_id="reconcile.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            observed_receipt_id=receipt.receipt_id,
        )
        assert replay.replayed is True
        assert backend.calls == 1

    asyncio.run(scenario())


def test_unsupported_cancel_stays_non_terminal_and_execution_finishes_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        backend = SlowUnsupportedToolExecutor()
        path = _path(tmp_path, backend)
        proposal = _browser_proposal("act.unsupported-cancel")
        execution = asyncio.create_task(path.execute(proposal))
        await backend.started.wait()

        receipt = await path.cancel_action(
            proposal.action_id,
            control_request_id="cancel.unsupported.1",
            expected_action_hash=canonical_action_hash(proposal),
            session_id="sense-session.1",
            principal="founder",
            reason="founder-explicit-cancel",
        )
        assert receipt.status == "unsupported"
        assert receipt.terminal is False
        assert execution.done() is False
        assert backend.cancel_calls == 0

        backend.release.set()
        result = await execution
        assert result.ok is True
        assert backend.calls == 1
        assert [event.event_type for event in path.event_bus.replay()].count(
            "action.cancel.unsupported"
        ) == 1
        assert not any(
            event.event_type == "action.canceled"
            for event in path.event_bus.replay()
        )

    asyncio.run(scenario())


def test_action_control_rejects_cross_session_hash_and_request_id_reuse(tmp_path: Path) -> None:
    async def scenario() -> None:
        backend = SlowCancellableToolExecutor()
        path = _path(tmp_path, backend)
        proposal = _browser_proposal("act.bound")
        execution = asyncio.create_task(path.execute(proposal))
        await backend.started.wait()
        with pytest.raises(ActionControlIntegrityError):
            await path.reconcile_action(
                proposal.action_id,
                control_request_id="control.shared",
                expected_action_hash="0" * 64,
                session_id="sense-session.1",
                principal="founder",
                observed_receipt_id="evt.unknown",
            )
        with pytest.raises(ActionControlIntegrityError):
            await path.reconcile_action(
                proposal.action_id,
                control_request_id="control.shared",
                expected_action_hash=canonical_action_hash(proposal),
                session_id="sense-session.other",
                principal="founder",
                observed_receipt_id="evt.unknown",
            )
        backend.release.set()
        assert (await execution).ok is True

    asyncio.run(scenario())
