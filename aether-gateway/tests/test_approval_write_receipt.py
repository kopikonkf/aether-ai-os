from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from aether.actions import FailureFingerprintStore, GovernedActionPath, PendingActionStore, TrustedApprovalInbox
from aether.cognition import AetherCognitiveGateway
from aether.contracts import (
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    ModelResponse,
    Perception,
)
from aether.events import EventBus
from aether.governance import ActionGovernor
from aether.senses import SenseEventPath
from aether_gateway.actions import RegistryToolExecutor
from aether_gateway.adapters import DirectTextSenseAdapter
from aether_gateway.approvals import ApprovalCoordinator
from aether_tools import ToolRegistry
from aether_tools.primitives import WriteTool


class SingleWriteModel:
    provider_id = "provider.single-write"

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    async def supports(self, capability):
        return True

    async def invoke(self, request):
        self.calls += 1
        return ModelResponse(
            content="Write the exact approved payload.",
            provider_id=self.provider_id,
            model_id="single-write-v1",
            action_proposals=(ActionProposal(
                ActionTarget.TOOL,
                "write",
                {"path": "workspace/experience.md", "content": self.content},
                (ActionScope.WRITE,),
                "Persist the Founder-requested reflection",
                ActionRisk.MEDIUM,
                False,
                correlation_id=request.correlation_id,
            ),),
        )


def test_successful_approved_write_uses_disk_receipt_without_second_model_generation(tmp_path: Path) -> None:
    aether_home = tmp_path / "aether-home"
    registry = ToolRegistry()
    registry.register(WriteTool([aether_home]))
    executor = RegistryToolExecutor(registry)
    action_bus = EventBus(tmp_path / "actions.jsonl")
    pending_store = PendingActionStore(tmp_path / "pending.sqlite3")
    action_path = GovernedActionPath(
        action_bus,
        ActionGovernor(),
        FailureFingerprintStore(tmp_path / "failures.jsonl"),
        tool_executor=executor,
        pending_store=pending_store,
    )
    expected_content = "# Exact content\nThis must match disk.\n"
    model = SingleWriteModel(expected_content)
    cognition = AetherCognitiveGateway(model, action_executor=action_path)
    sense_path = SenseEventPath(EventBus(tmp_path / "sense.jsonl"), cognition)
    adapter = DirectTextSenseAdapter(adapter_id="sense.test")

    asyncio.run(sense_path.handle(adapter, Perception(
        modality="http.text",
        content="Write the experience file",
        source="telegram:99",
        metadata={"channel": "telegram", "chat_id": 99, "user_id": 7, "session_id": "telegram:99"},
    )))
    approval_id = adapter.expressions[-1].metadata["pending_approval"]["approval_id"]
    assert model.calls == 1

    coordinator = ApprovalCoordinator(
        TrustedApprovalInbox(pending_store, action_path, action_bus),
        cognition,
    )
    outcome = asyncio.run(coordinator.decide(
        approval_id,
        approved=True,
        principal="telegram:7",
        reason="Founder approved once via trusted Telegram session",
        channel="telegram",
    ))

    target = aether_home / "workspace" / "experience.md"
    assert target.read_text(encoding="utf-8") == expected_content
    expected_hash = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()
    assert model.calls == 1
    assert outcome.expression is not None
    assert expected_hash in outcome.expression.content
    assert "Waiting for operator approval" not in outcome.expression.content
    assert "menunggu trusted operator approval" not in outcome.expression.content
    assert outcome.expression.metadata["action_result"]["metadata"]["data"]["sha256"] == expected_hash
