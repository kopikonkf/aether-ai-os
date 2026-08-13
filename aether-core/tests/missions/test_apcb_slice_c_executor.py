"""Slice C scaffold — ApcbMissionActionExecutor wiring (deterministic).

MISSION-PCP-001 Slice C: MissionOrchestrator stays the owner of mission
semantics; APCB is the deterministic execution coordinator. These tests use a
stub dispatcher (DispatchDecision built directly) — NO live herdr, NO real
APCB dispatch.

Division under test:
  - ApcbMissionActionExecutor.execute maps ActionProposal -> WorkItemView
    (via the caller-provided work_mapper) and translates the APCB
    DispatchDecision back into an ActionResult.
  - MissionOrchestrator.run() drives mission semantics (plan/step/budget/
    approval/outcome) while the step execution is delegated to APCB.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from aether.apcb.dispatcher import DispatchDecision
from aether.apcb.eligibility import WorkItemView
from aether.contracts import (
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    MissionBlocked,
    MissionBudget,
    MissionLane,
    MissionRisk,
    MissionStatus,
    MissionStep,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.contracts.actions import ActionResult
from aether.events import EventBus
from aether.missions import MissionOrchestrator, SQLiteMissionStore
from aether.missions.apcb_executor import ApcbMissionActionExecutor


class StubDispatcher:
    """Deterministic APCBDispatcher stand-in: returns a preset decision."""

    def __init__(self, decision: DispatchDecision) -> None:
        self.decision = decision
        self.last_work: WorkItemView | None = None

    def dispatch(self, work: WorkItemView) -> DispatchDecision:
        self.last_work = work
        return self.decision


def make_work_mapper() -> Callable[[ActionProposal, int], WorkItemView]:
    """Caller-provided mapper: mission step -> canonical APCB work item."""

    def mapper(action: ActionProposal, attempt: int) -> WorkItemView:
        meta = dict(action.metadata or {})
        return WorkItemView(
            work_id=f"WORK-{action.action_id}",
            mission_id=str(meta.get("mission_id") or "MISSION-PCP-001"),
            principal_id="qwen",
            required_capabilities=("coding",),
            workspace_id=str(meta.get("workspace_id") or "workspace://default"),
            authorized=True,
            execution_ready=True,
            awaiting_approval=bool(meta.get("awaiting_approval")),
            attempt_number=attempt,
            execution_profile="herdr:cline",
            metadata={"objective": action.operation},
        )

    return mapper


def decision(
    *, status: str = "dispatched", outcome: str = "completed",
    diagnostic=(), metadata=None,
) -> DispatchDecision:
    return DispatchDecision(
        work_id="WORK-1",
        mission_id="MISSION-PCP-001",
        principal_id="qwen",
        attempt_number=1,
        dispatched=status == "dispatched",
        status=status,
        terminal_outcome=outcome,
        diagnostic=tuple(diagnostic),
        metadata=dict(metadata or {}),
    )


def proposal(operation: str = "implement", **metadata) -> ActionProposal:
    return ActionProposal(
        target=ActionTarget.RUNTIME,
        operation=operation,
        required_scopes=(ActionScope.EXECUTE,),
        reason="Bounded step.",
        risk=ActionRisk.LOW,
        reversible=True,
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_execute_completed_ok():
    disp = StubDispatcher(decision(status="dispatched", outcome="completed", metadata={"output_tail": "done"}))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is True
    assert result.status == "completed"
    assert result.output == "done"
    assert result.error is None
    assert disp.last_work is not None
    assert disp.last_work.attempt_number == 1


@pytest.mark.asyncio
async def test_execute_forwards_attempt_from_proposal_metadata():
    # MISSION-PCP-002 WORK-1: attempt from proposal.metadata["mission_attempt_number"].
    seen: list[int] = []

    def recording_mapper(action: ActionProposal, attempt: int) -> WorkItemView:
        seen.append(attempt)
        return make_work_mapper()(action, attempt)

    disp = StubDispatcher(decision(status="dispatched", outcome="completed", metadata={"output_tail": "ok"}))
    executor = ApcbMissionActionExecutor(disp, recording_mapper)
    result = await executor.execute(proposal(mission_attempt_number=3))
    assert result.ok is True
    assert seen == [3]
    assert disp.last_work is not None
    assert disp.last_work.attempt_number == 3


@pytest.mark.asyncio
async def test_execute_defaults_attempt_1():
    disp = StubDispatcher(decision(status="dispatched", outcome="completed", metadata={"output_tail": "ok"}))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is True
    assert disp.last_work is not None
    assert disp.last_work.attempt_number == 1


@pytest.mark.asyncio
async def test_execute_reconcile_promoted_completed_ok():
    # MISSION-PCP-002 live smoke finding: a second dispatch reconciles an
    # existing receipt whose terminal was unknown/failed but the artifact now
    # exists -> dispatcher returns status="promoted", outcome="completed"
    # (reconcile_artifact_found). This must map to ok=True (completed step),
    # not fall through to the ok=False fallback.
    disp = StubDispatcher(
        decision(
            status="promoted",
            outcome="completed",
            metadata={"reconcile_artifact_found": True, "output_tail": "delivered"},
        )
    )
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is True
    assert result.status == "completed"
    assert result.metadata.get("reconcile_artifact_found") is True
    assert result.error is None


@pytest.mark.asyncio
async def test_execute_failed_ok_false_with_diagnostic():
    disp = StubDispatcher(decision(status="failed", outcome="failed", diagnostic=("herdr agent gone during dispatch",)))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is False
    assert result.status == "failed"
    assert "herdr agent gone" in (result.error or "")
    assert result.metadata.get("apcb_status") == "failed"


@pytest.mark.asyncio
async def test_execute_rejected_ok_false():
    disp = StubDispatcher(decision(status="rejected", outcome="rejected", diagnostic=("eligibility:not_authorized",)))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is False
    assert result.status == "rejected"
    assert "not_authorized" in (result.error or "")


@pytest.mark.asyncio
async def test_execute_completed_without_artifact_marks_missing():
    disp = StubDispatcher(decision(status="dispatched", outcome="completed_without_artifact", metadata={"output_tail": "x"}))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal())
    assert result.ok is True
    assert result.metadata.get("artifact_missing") is True


@pytest.mark.asyncio
async def test_execute_pending_approval_passthrough():
    # work_mapper sets awaiting_approval from action.metadata -> no APCB call.
    disp = StubDispatcher(decision(status="rejected", outcome="rejected"))
    executor = ApcbMissionActionExecutor(disp, make_work_mapper())
    result = await executor.execute(proposal(awaiting_approval=True))
    assert result.status == "pending-approval"
    assert result.ok is False
    assert disp.last_work is None  # APCB was not asked to dispatch


@pytest.mark.asyncio
async def test_approval_result_always_none():
    executor = ApcbMissionActionExecutor(StubDispatcher(decision()), make_work_mapper())
    assert await executor.approval_result("approval-1") is None


# ---------------------------------------------------------------------------
# Integration: MissionOrchestrator stays owner, APCB executes the step
# ---------------------------------------------------------------------------
def make_orchestrator(tmp_path: Path, decision: DispatchDecision):
    store = SQLiteMissionStore(tmp_path / "missions.sqlite3")
    executor = ApcbMissionActionExecutor(StubDispatcher(decision), make_work_mapper())
    orchestrator = MissionOrchestrator(
        store,
        executor,
        event_bus=EventBus(tmp_path / "events.jsonl"),
        maximum_steps_per_run=5,
    )
    return orchestrator, store


def make_brief(orchestrator: MissionOrchestrator):
    return orchestrator.intake_opportunity(
        title="Bounded market validation",
        lane=MissionLane.EXTERNAL_VALUE,
        problem_statement="A narrow customer segment has an unverified workflow problem.",
        beneficiary="Small operators",
        value_proposition="Reduce repetitive work through a bounded service experiment.",
        probability_success=0.5,
        upside_usd=100.0,
        estimated_cost_usd=10.0,
        estimated_duration_hours=2.0,
        revenue_hypothesis="One customer pays USD 100 after accepting the deliverable.",
        assumptions=("Demand remains stable during the experiment.",),
        evidence=(evidence("a"), evidence("b")),
        risk=MissionRisk.LOW,
        confidence=0.6,
    )


def evidence(source: str, *, stance: OpportunityEvidenceStance = OpportunityEvidenceStance.SUPPORTS):
    return OpportunityEvidence(
        source=source,
        independent_source_id=source,
        statement=f"Evidence from {source}",
        stance=stance,
        external_reference=f"https://evidence.invalid/{source}",
    )


def make_plan(orchestrator: MissionOrchestrator, brief_id: str, operation: str = "read"):
    plan = orchestrator.create_plan(
        brief_id=brief_id,
        objective="Validate one bounded opportunity without scaling automatically.",
        northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
        northstar_principle_ids=("SP1", "SP5"),
        strategy_tags=("business_experimentation",),
        steps=(
            MissionStep(
                step_id="step-1",
                title="Step 1",
                action=ActionProposal(
                    target=ActionTarget.RUNTIME,
                    operation=operation,
                    required_scopes=(ActionScope.EXECUTE,),
                    reason="Run bounded step.",
                    risk=ActionRisk.LOW,
                    reversible=True,
                ),
                success_criteria=("Backend returns a governed successful result.",),
                depends_on=(),
                max_attempts=1,
                estimated_cost_usd=1.0,
            ),
        ),
        budget=MissionBudget(max_cost_usd=10.0, max_duration_seconds=3600, max_step_attempts=10),
        stop_conditions=("Stop when budget is exhausted.",),
    )
    return plan


@pytest.mark.asyncio
async def test_orchestrator_runs_mission_through_apcb_completed(tmp_path):
    orchestrator, store = make_orchestrator(
        tmp_path, decision(status="dispatched", outcome="completed", metadata={"output_tail": "ok"})
    )
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    result = await orchestrator.run(plan.mission_id, principal="founder")
    assert result.status == MissionStatus.COMPLETED
    assert result.completed_step_ids == ("step-1",)
    assert store.current_status(plan.mission_id) == MissionStatus.COMPLETED
    attempts = store.attempts(plan.mission_id, step_id="step-1")
    assert len(attempts) == 1
    assert attempts[0].status.value == "completed"


@pytest.mark.asyncio
async def test_orchestrator_fails_step_when_apcb_rejects(tmp_path):
    orchestrator, _ = make_orchestrator(
        tmp_path, decision(status="rejected", outcome="rejected", diagnostic=("eligibility:not_authorized",))
    )
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    result = await orchestrator.run(plan.mission_id, principal="founder")
    assert result.status == MissionStatus.FAILED
    attempts = orchestrator.store.attempts(plan.mission_id, step_id="step-1")
    assert attempts[-1].status.value == "failed"


# ---------------------------------------------------------------------------
# MISSION-PCP-002 WORK-1: attempt_number wired into APCB attempt
# ---------------------------------------------------------------------------
class RecordingExecutor:
    """MissionActionExecutor stub that records every ActionProposal received."""

    def __init__(self, result_factory: Callable[[int], ActionResult]):
        self.result_factory = result_factory
        self.seen: list[ActionProposal] = []

    async def execute(self, proposal: ActionProposal) -> ActionResult:
        self.seen.append(proposal)
        return self.result_factory(len(self.seen))

    async def approval_result(self, approval_id: str) -> ActionResult | None:
        return None


def completed_result(action_id: str) -> ActionResult:
    return ActionResult(action_id=action_id, ok=True, status="completed", output="ok")


def failed_result(action_id: str) -> ActionResult:
    return ActionResult(action_id=action_id, ok=False, status="failed", error="transient step failure")


def make_orchestrator_with_executor(tmp_path: Path, executor: RecordingExecutor):
    store = SQLiteMissionStore(tmp_path / "missions.sqlite3")
    orchestrator = MissionOrchestrator(
        store,
        executor,
        event_bus=EventBus(tmp_path / "events.jsonl"),
        maximum_steps_per_run=5,
    )
    return orchestrator, store


def make_plan_attempt(orchestrator: MissionOrchestrator, brief_id: str, *, max_attempts: int = 1,
                      stop_on_failure: bool = True, explicit_retry_reason: str | None = None):
    plan = orchestrator.create_plan(
        brief_id=brief_id,
        objective="Validate one bounded opportunity without scaling automatically.",
        northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
        northstar_principle_ids=("SP1", "SP5"),
        strategy_tags=("business_experimentation",),
        steps=(
            MissionStep(
                step_id="step-1",
                title="Step 1",
                action=ActionProposal(
                    target=ActionTarget.RUNTIME,
                    operation="read",
                    required_scopes=(ActionScope.EXECUTE,),
                    reason="Run bounded step.",
                    risk=ActionRisk.LOW,
                    reversible=True,
                ),
                success_criteria=("Backend returns a governed successful result.",),
                depends_on=(),
                max_attempts=max_attempts,
                stop_on_failure=stop_on_failure,
                explicit_retry_reason=explicit_retry_reason,
                estimated_cost_usd=1.0,
            ),
        ),
        budget=MissionBudget(max_cost_usd=10.0, max_duration_seconds=3600, max_step_attempts=10),
        stop_conditions=("Stop when budget is exhausted.",),
    )
    return plan


@pytest.mark.asyncio
async def test_orchestrator_metadata_carries_attempt_number(tmp_path):
    executor = RecordingExecutor(completed_result)
    orchestrator, store = make_orchestrator_with_executor(tmp_path, executor)
    brief = make_brief(orchestrator)
    plan = make_plan_attempt(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    result = await orchestrator.run(plan.mission_id, principal="founder")
    assert result.status == MissionStatus.COMPLETED
    assert len(executor.seen) == 1
    assert executor.seen[0].metadata.get("mission_attempt_number") == 1
    attempts = store.attempts(plan.mission_id, step_id="step-1")
    assert attempts[0].attempt_number == 1


@pytest.mark.asyncio
async def test_orchestrator_retry_increments_attempt(tmp_path):
    # Attempt 1 fails (ok=False), attempt 2 completes; explicit_retry_reason set
    # so the orchestrator retries without pausing for a new reason.
    def attempt_result(index: int) -> ActionResult:
        if index == 1:
            return failed_result(f"act-{index}")
        return completed_result(f"act-{index}")

    executor = RecordingExecutor(attempt_result)
    orchestrator, store = make_orchestrator_with_executor(tmp_path, executor)
    brief = make_brief(orchestrator)
    plan = make_plan_attempt(orchestrator, brief.brief_id, max_attempts=2, stop_on_failure=False,
                             explicit_retry_reason="transient infrastructure failure; safe to retry")
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    result = await orchestrator.run(plan.mission_id, principal="founder")
    assert result.status == MissionStatus.COMPLETED
    assert [item.metadata.get("mission_attempt_number") for item in executor.seen] == [1, 2]
    attempts = store.attempts(plan.mission_id, step_id="step-1")
    assert [item.attempt_number for item in attempts] == [1, 2]
    assert attempts[-1].status.value == "completed"
