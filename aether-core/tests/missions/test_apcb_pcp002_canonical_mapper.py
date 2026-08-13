"""MISSION-PCP-002 WORK-2 — canonical governed work_mapper.

Tests for build_canonical_work_mapper (aether.missions.canonical_mapper):
principal_id / execution_profile / workspace_id / capabilities are derived from
canonical mission action metadata + the principal profile registry, fail-closed
(empty fields, no raise) when unassignable. Also covers the executor wiring:
work_mapper=None + profiles -> canonical mapper; both None -> ValueError.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aether.apcb.dispatcher import DispatchDecision
from aether.apcb.eligibility import EligibilityEvaluator, WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.missions.apcb_executor import ApcbMissionActionExecutor
from aether.missions.canonical_mapper import build_canonical_work_mapper


def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


def proposal(**metadata: Any) -> ActionProposal:
    return ActionProposal(
        target=ActionTarget.RUNTIME,
        operation="implement",
        required_scopes=(ActionScope.EXECUTE,),
        reason="Bounded step.",
        risk=ActionRisk.LOW,
        reversible=True,
        metadata=metadata,
    )


def decision() -> DispatchDecision:
    return DispatchDecision(
        work_id="WORK-1",
        mission_id="MISSION-PCP-002",
        principal_id="qwen",
        attempt_number=1,
        dispatched=True,
        status="dispatched",
        terminal_outcome="completed",
        metadata={"output_tail": "done"},
    )


class StubDispatcher:
    def __init__(self, decision: DispatchDecision) -> None:
        self.decision = decision
        self.last_work: WorkItemView | None = None

    def dispatch(self, work: WorkItemView) -> DispatchDecision:
        self.last_work = work
        return self.decision


def test_canonical_mapper_derives_profile_from_metadata():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(mission_principal_id="qwen", mission_execution_profile="herdr:cline"), attempt=3)
    assert work.principal_id == "qwen"
    assert work.execution_profile == "herdr:cline"
    assert work.attempt_number == 3


def test_canonical_mapper_derives_profile_from_registry():
    reg = profiles()
    mapper = build_canonical_work_mapper(reg)
    work = mapper(proposal(mission_principal_id="qwen"), attempt=1)
    assert work.principal_id == "qwen"
    assert work.execution_profile == "herdr:cline"


def test_canonical_mapper_fail_closed_no_principal(tmp_path: Path):
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(), attempt=1)
    assert work.principal_id == ""
    assert work.execution_profile == ""
    eligibility = EligibilityEvaluator(profiles(), ReceiptStore(tmp_path / "receipts.jsonl")).evaluate(work)
    assert eligibility.principal_assigned is False
    assert "principal_assigned" in eligibility.blockers()


def test_canonical_mapper_fail_closed_unknown_principal():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(mission_principal_id="ghost"), attempt=1)
    assert work.principal_id == "ghost"
    assert work.execution_profile == ""


def test_canonical_mapper_fields():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(
        proposal(
            mission_principal_id="qwen",
            mission_execution_profile="herdr:cline",
            mission_workspace_id="workspace://aether-v2",
            mission_capabilities=("coding", "testing"),
            mission_authorized=False,
            mission_execution_ready=False,
            mission_awaiting_approval=True,
            mission_work_id="WORK-OVERRIDE",
        ),
        attempt=2,
    )
    assert work.workspace_id == "workspace://aether-v2"
    assert work.required_capabilities == ("coding", "testing")
    assert work.authorized is False
    assert work.execution_ready is False
    assert work.awaiting_approval is True
    assert work.work_id == "WORK-OVERRIDE"


def test_canonical_mapper_legacy_aliases():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(mission_principal_id="qwen", workspace_id="workspace://legacy", awaiting_approval=True), attempt=1)
    assert work.workspace_id == "workspace://legacy"
    assert work.awaiting_approval is True


@pytest.mark.asyncio
async def test_executor_uses_canonical_mapper_when_work_mapper_none():
    disp = StubDispatcher(decision())
    executor = ApcbMissionActionExecutor(disp, None, profiles=profiles())
    result = await executor.execute(proposal(
        mission_principal_id="qwen",
        mission_execution_profile="herdr:cline",
        mission_workspace_id="workspace://aether-v2",
        mission_attempt_number=2,
    ))
    assert result.ok is True
    assert disp.last_work is not None
    assert disp.last_work.principal_id == "qwen"
    assert disp.last_work.execution_profile == "herdr:cline"
    assert disp.last_work.workspace_id == "workspace://aether-v2"
    assert disp.last_work.attempt_number == 2


def test_executor_raises_without_mapper_and_profiles():
    with pytest.raises(ValueError):
        ApcbMissionActionExecutor(StubDispatcher(decision()), None, profiles=None)
