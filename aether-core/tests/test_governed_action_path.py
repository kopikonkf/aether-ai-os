from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aether.actions import FailureFingerprintStore, GovernedActionPath
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
