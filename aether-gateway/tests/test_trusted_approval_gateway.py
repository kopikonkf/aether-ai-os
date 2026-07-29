from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
from aether.cognition import AetherCognitiveGateway
from aether.contracts import (
    ActionCapability,
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    ModelResponse,
    Perception,
    RuntimeResult,
)
from aether.events import EventBus
from aether.governance import ActionGovernor
from aether.senses import SenseEventPath
from aether_gateway.adapters import DirectTextSenseAdapter
from aether_gateway.approvals import ApprovalCoordinator, OperatorAuthError, OperatorAuthenticator


class WriteExecutor:
    def __init__(self):
        self.calls = 0

    async def capabilities(self):
        return [ActionCapability(ActionTarget.TOOL, "write", "write", (ActionScope.WRITE,), False, {})]

    async def execute_tool(self, operation, arguments):
        self.calls += 1
        return RuntimeResult(True, output={"path": arguments["path"], "written": True})


class ApprovalModel:
    provider_id = "provider.approval-test"

    async def supports(self, capability):
        return True

    async def invoke(self, request):
        if any("Governed action results" in str(message.get("content", "")) for message in request.messages):
            return ModelResponse(
                content="Artifact written after trusted founder approval.",
                provider_id=self.provider_id,
                model_id="approval-v1",
            )
        return ModelResponse(
            content="A bounded write is required.",
            provider_id=self.provider_id,
            model_id="approval-v1",
            action_proposals=(ActionProposal(
                ActionTarget.TOOL,
                "write",
                {"path": "approved.txt", "content": "verified"},
                (ActionScope.WRITE,),
                "Persist the requested verified artifact",
                ActionRisk.MEDIUM,
                False,
                correlation_id=request.correlation_id,
            ),),
        )


def test_pending_approval_resumes_cognition_after_exact_once_execution(tmp_path: Path) -> None:
    backend = WriteExecutor()
    action_bus = EventBus(tmp_path / "actions.jsonl")
    store = PendingActionStore(tmp_path / "pending.sqlite3")
    action_path = GovernedActionPath(
        action_bus,
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
        pending_store=store,
    )
    cognition = AetherCognitiveGateway(ApprovalModel(), action_executor=action_path)
    sense_path = SenseEventPath(EventBus(tmp_path / "sense.jsonl"), cognition)
    adapter = DirectTextSenseAdapter(adapter_id="sense.test")

    asyncio.run(sense_path.handle(adapter, Perception(
        modality="http.text",
        content="Write the approved artifact",
        source="http:test",
        metadata={"channel": "http", "session_id": "http:test", "response_modality": "text"},
    )))
    first_expression = adapter.expressions[-1]
    approval_id = first_expression.metadata["pending_approval"]["approval_id"]
    assert "menunggu trusted operator approval" in first_expression.content
    assert store.get(approval_id).continuation is not None
    assert backend.calls == 0

    inbox = TrustedApprovalInbox(store, action_path, action_bus)
    coordinator = ApprovalCoordinator(inbox, cognition)
    outcome = asyncio.run(coordinator.decide(
        approval_id,
        approved=True,
        principal="founder",
        reason="Exact write payload reviewed",
        channel="http",
    ))
    assert backend.calls == 1
    assert outcome.expression is not None
    assert "Status: completed" in outcome.expression.content
    assert "Approval ID:" in outcome.expression.content
    assert "Tidak ada approval tambahan" in outcome.expression.content
    assert outcome.expression.metadata["authoritative_receipt"] is True
    assert outcome.expression.metadata["model_continuation"] is False

    replay = asyncio.run(coordinator.decide(
        approval_id,
        approved=True,
        principal="founder",
        reason="Browser retried request",
        channel="http",
    ))
    assert replay.approval.replayed
    assert replay.expression is None
    assert backend.calls == 1


def test_operator_authenticator_is_fail_closed_and_constant_identity() -> None:
    disabled = OperatorAuthenticator(token="", principal="founder")
    with pytest.raises(OperatorAuthError):
        disabled.authenticate("anything")
    auth = OperatorAuthenticator(token="secret-token", principal="founder")
    with pytest.raises(OperatorAuthError):
        auth.authenticate("wrong")
    operator = auth.authenticate("secret-token", channel="http")
    assert operator.principal == "founder"
    assert operator.channel == "http"


class FailingWriteExecutor(WriteExecutor):
    async def execute_tool(self, operation, arguments):
        self.calls += 1
        return RuntimeResult(False, error="Write access denied; target is outside configured roots: D:\\\\")


class CountingApprovalModel(ApprovalModel):
    def __init__(self):
        self.calls = 0

    async def invoke(self, request):
        self.calls += 1
        return await super().invoke(request)


def test_failed_approved_action_is_reported_without_model_retry(tmp_path: Path) -> None:
    backend = FailingWriteExecutor()
    model = CountingApprovalModel()
    action_bus = EventBus(tmp_path / "actions.jsonl")
    store = PendingActionStore(tmp_path / "pending.sqlite3")
    action_path = GovernedActionPath(
        action_bus,
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=backend,
        pending_store=store,
    )
    cognition = AetherCognitiveGateway(model, action_executor=action_path)
    sense_path = SenseEventPath(EventBus(tmp_path / "sense.jsonl"), cognition)
    adapter = DirectTextSenseAdapter(adapter_id="sense.test")

    asyncio.run(sense_path.handle(adapter, Perception(
        modality="http.text",
        content="Write the approved artifact",
        source="http:test",
        metadata={"channel": "http", "session_id": "http:test", "response_modality": "text"},
    )))
    approval_id = adapter.expressions[-1].metadata["pending_approval"]["approval_id"]
    initial_model_calls = model.calls

    coordinator = ApprovalCoordinator(TrustedApprovalInbox(store, action_path, action_bus), cognition)
    outcome = asyncio.run(coordinator.decide(
        approval_id,
        approved=True,
        principal="founder",
        reason="Exact payload reviewed",
        channel="http",
    ))
    assert backend.calls == 1
    assert model.calls == initial_model_calls
    assert outcome.expression is not None
    assert "did not retry automatically" in outcome.expression.content
    assert "outside configured roots" in outcome.expression.content
