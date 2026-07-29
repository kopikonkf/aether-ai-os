from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from aether.contracts import (
    ActionResult, CodingEdit, CodingExecutionStatus, CodingTask, RuntimeDescriptor,
    RuntimeHealthStatus, VerificationCommand, WorkspaceBinding,
)
from aether.runtimes import CodingRuntimePolicy, CodingRuntimeRouter, CodingRoutedActionExecutor


class Directory:
    def __init__(self, descriptors):
        self.descriptors = descriptors

    async def discover(self):
        return tuple(self.descriptors)


class Bindings:
    def __init__(self, root: Path):
        self.root = root

    def resolve(self, workspace_id: str, session_id: str):
        return WorkspaceBinding(workspace_id, str(self.root), session_id)


class Executor:
    def __init__(self, results):
        self.results = list(results)
        self.proposals = []

    async def capabilities(self):
        return ()

    async def execute(self, proposal, approval=None):
        self.proposals.append(proposal)
        return self.results.pop(0)

    async def save_continuation(self, approval_id, continuation):
        return None


def descriptor(*, healthy=True, priority=10, routing_key="runtime://coding/test", capabilities=("coding.edit",)):
    return RuntimeDescriptor(
        routing_key=routing_key,
        adapter_id=routing_key.rsplit("/", 1)[-1],
        display_name="Test Runtime",
        operations=("coding.task.execute",),
        capabilities=capabilities,
        runtime_features=("structured-edits",),
        health_status=RuntimeHealthStatus.HEALTHY if healthy else RuntimeHealthStatus.UNAVAILABLE,
        priority=priority,
    )


def task(tmp_path: Path, **changes):
    data = dict(
        objective="Fix arithmetic implementation.",
        workspace_id="workspace-1",
        session_id="session-1",
        edits=(CodingEdit("calc.py", "def add(a,b): return a+b\n"),),
        verification_commands=(VerificationCommand(("python", "-m", "compileall", "."), label="compile"),),
        required_runtime_features=("structured-edits",),
    )
    data.update(changes)
    return CodingTask(**data)


def test_router_creates_private_governed_body_action(tmp_path: Path):
    executor = Executor([ActionResult("act-1", False, "pending-approval", metadata={"approval_id": "approval-1"})])
    router = CodingRuntimeRouter(Directory([descriptor()]), Bindings(tmp_path), executor)
    result = asyncio.run(router.execute(task(tmp_path)))
    assert result.status == CodingExecutionStatus.PENDING_APPROVAL
    proposal = executor.proposals[0]
    assert proposal.operation == "coding.task.execute"
    assert proposal.metadata["runtime_id"] == "runtime://coding/dispatch"
    assert proposal.arguments["runtime_candidates"][0]["routing_key"] == "runtime://coding/test"
    assert {scope.value for scope in proposal.required_scopes} == {"read", "write", "execute"}
    assert proposal.arguments["workspace_binding"]["root_path"] == str(tmp_path)


def test_router_filters_unhealthy_and_escalates(tmp_path: Path):
    router = CodingRuntimeRouter(Directory([descriptor(healthy=False)]), Bindings(tmp_path), Executor([]))
    result = asyncio.run(router.execute(task(tmp_path)))
    assert result.status == CodingExecutionStatus.ESCALATED
    assert result.failure_fingerprint
    assert "health" in " ".join(result.blockers)


def test_router_accepts_dispatch_fallback_result(tmp_path: Path):
    executor = Executor([
        ActionResult(
            "act-1", True, "completed", output={"ok": True},
            metadata={
                "selected_runtime_adapter_id": "second",
                "runtime_attempts": [
                    {"attempt": 1, "runtime_adapter_id": "first", "ok": False},
                    {"attempt": 2, "runtime_adapter_id": "second", "ok": True},
                ],
            },
        ),
    ])
    router = CodingRuntimeRouter(
        Directory([descriptor(priority=1, routing_key="runtime://coding/first"), descriptor(priority=2, routing_key="runtime://coding/second")]),
        Bindings(tmp_path), executor,
    )
    result = asyncio.run(router.execute(task(tmp_path)))
    assert result.status == CodingExecutionStatus.FALLBACK_COMPLETED
    assert result.selected_runtime_id == "second"
    assert len(result.attempts) == 2
    assert len(executor.proposals) == 1


def test_write_task_requires_verification(tmp_path: Path):
    router = CodingRuntimeRouter(Directory([descriptor()]), Bindings(tmp_path), Executor([]))
    result = asyncio.run(router.execute(task(tmp_path, verification_commands=())))
    assert result.status == CodingExecutionStatus.BLOCKED
    assert "verification" in " ".join(result.blockers)


def test_coding_route_is_visible_but_body_operation_is_hidden(tmp_path: Path):
    executor = Executor([])
    router = CodingRuntimeRouter(Directory([descriptor()]), Bindings(tmp_path), executor)
    wrapped = CodingRoutedActionExecutor(executor, router)
    capabilities = asyncio.run(wrapped.capabilities())
    operations = {item.operation for item in capabilities}
    assert "coding.delegate" in operations
    assert "coding.task.execute" not in operations
