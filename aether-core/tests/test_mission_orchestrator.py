from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from aether.contracts import (
    ActionProposal,
    ActionResult,
    ActionRisk,
    ActionScope,
    ActionTarget,
    MissionBlocked,
    MissionBudget,
    MissionLane,
    MissionOutcomeState,
    MissionRisk,
    MissionStatus,
    MissionStep,
    MissionValueKind,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.events import EventBus
from aether.missions import MissionOrchestrator, SQLiteMissionStore


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.approvals: dict[str, ActionResult | None] = {}

    async def execute(self, proposal: ActionProposal) -> ActionResult:
        self.calls.append(proposal.operation)
        if proposal.operation == "needs-approval":
            self.approvals.setdefault("approval-1", None)
            return ActionResult(proposal.action_id, False, "pending-approval", metadata={"approval_id": "approval-1"})
        if proposal.operation == "fail":
            return ActionResult(proposal.action_id, False, "failed", error="deterministic failure", failure_fingerprint="fp-1")
        return ActionResult(proposal.action_id, True, "completed", output={"operation": proposal.operation})

    async def approval_result(self, approval_id: str) -> ActionResult | None:
        return self.approvals.get(approval_id)


class FakeEvolution:
    def __init__(self) -> None:
        self.triggers = []

    def register_trigger(self, trigger):
        trigger = replace(trigger, created_at="2026-07-28T00:00:00+00:00")
        self.triggers.append(trigger)
        return trigger


def evidence(source: str, *, stance: OpportunityEvidenceStance = OpportunityEvidenceStance.SUPPORTS):
    return OpportunityEvidence(
        source=source,
        independent_source_id=source,
        statement=f"Evidence from {source}",
        stance=stance,
        external_reference=f"https://evidence.invalid/{source}",
    )


def make_orchestrator(tmp_path: Path, *, evolution=None, maximum_steps_per_run: int = 5):
    executor = FakeExecutor()
    store = SQLiteMissionStore(tmp_path / "missions.sqlite3")
    orchestrator = MissionOrchestrator(
        store,
        executor,
        event_bus=EventBus(tmp_path / "events.jsonl"),
        evolution_engine=evolution,
        maximum_steps_per_run=maximum_steps_per_run,
    )
    return orchestrator, store, executor


def make_brief(orchestrator: MissionOrchestrator, *, evidence_items=None, lane=MissionLane.EXTERNAL_VALUE):
    return orchestrator.intake_opportunity(
        title="Bounded market validation",
        lane=lane,
        problem_statement="A narrow customer segment has an unverified workflow problem.",
        beneficiary="Small operators",
        value_proposition="Reduce repetitive work through a bounded service experiment.",
        probability_success=0.5,
        upside_usd=100.0,
        estimated_cost_usd=10.0,
        estimated_duration_hours=2.0,
        revenue_hypothesis="One customer pays USD 100 after accepting the deliverable.",
        assumptions=("Demand remains stable during the experiment.",),
        evidence=tuple(evidence_items or (evidence("a"), evidence("b"))),
        risk=MissionRisk.LOW,
        confidence=0.6,
    )


def make_plan(orchestrator: MissionOrchestrator, brief_id: str, operations=("read",), *, budget=None):
    steps = []
    prior = None
    for index, operation in enumerate(operations, start=1):
        step_id = f"step-{index}"
        steps.append(MissionStep(
            step_id=step_id,
            title=f"Step {index}",
            action=ActionProposal(
                target=ActionTarget.RUNTIME,
                operation=operation,
                required_scopes=(ActionScope.EXECUTE,),
                reason=f"Run bounded step {index}.",
                risk=ActionRisk.LOW,
                reversible=True,
            ),
            success_criteria=("Backend returns a governed successful result.",),
            depends_on=(prior,) if prior else (),
            max_attempts=1,
            estimated_cost_usd=1.0,
        ))
        prior = step_id
    return orchestrator.create_plan(
        brief_id=brief_id,
        objective="Validate one bounded opportunity without scaling automatically.",
        northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
        northstar_principle_ids=("SP1", "SP5"),
        strategy_tags=("business_experimentation",),
        steps=steps,
        budget=budget or MissionBudget(max_cost_usd=10.0, max_duration_seconds=3600, max_step_attempts=10),
        stop_conditions=("Stop when budget is exhausted.", "Stop on unresolved contradiction."),
    )


def test_external_opportunity_requires_independent_evidence(tmp_path):
    orchestrator, _, _ = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator, evidence_items=(evidence("same"), evidence("same")))
    assert brief.independent_support_count == 1
    assert "independent supporting sources" in " ".join(brief.blockers)
    with pytest.raises(MissionBlocked):
        make_plan(orchestrator, brief.brief_id)


def test_contradiction_blocks_mission_plan(tmp_path):
    orchestrator, _, _ = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator, evidence_items=(evidence("a"), evidence("b"), evidence("c", stance=OpportunityEvidenceStance.CONTRADICTS)))
    assert brief.contradiction_evidence_ids
    with pytest.raises(MissionBlocked, match="contradiction"):
        make_plan(orchestrator, brief.brief_id)


def test_trusted_decision_and_bounded_pause_resume(tmp_path):
    orchestrator, store, executor = make_orchestrator(tmp_path, maximum_steps_per_run=1)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id, operations=("one", "two"))
    with pytest.raises(MissionBlocked, match="trusted"):
        orchestrator.decide(plan.mission_id, approved=True, principal="model", channel="internal", reason="self approve")
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Reviewed evidence and budget.")
    first = asyncio.run(orchestrator.run(plan.mission_id, principal="founder", maximum_steps=1))
    assert first.status == MissionStatus.PAUSED
    assert first.completed_step_ids == ("step-1",)
    second = asyncio.run(orchestrator.run(plan.mission_id, principal="founder", maximum_steps=1))
    assert second.status == MissionStatus.COMPLETED
    assert executor.calls == ["one", "two"]
    assert store.current_status(plan.mission_id) == MissionStatus.COMPLETED


def test_pending_approval_resumes_exact_step_once(tmp_path):
    orchestrator, store, executor = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id, operations=("needs-approval",))
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve mission plan only.")
    first = asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    assert first.status == MissionStatus.WAITING_APPROVAL
    assert first.approval_id == "approval-1"
    assert executor.calls == ["needs-approval"]
    executor.approvals["approval-1"] = ActionResult("action-approved", True, "completed", output={"verified": True})
    second = asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    assert second.status == MissionStatus.COMPLETED
    assert executor.calls == ["needs-approval"]
    attempts = store.attempts(plan.mission_id, step_id="step-1")
    assert [item.status.value for item in attempts] == ["waiting-approval", "completed"]


def test_budget_stop_prevents_execution(tmp_path):
    orchestrator, store, executor = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    with pytest.raises(MissionBlocked, match="estimated step cost"):
        make_plan(
            orchestrator,
            brief.brief_id,
            operations=("one", "two"),
            budget=MissionBudget(max_cost_usd=1.0, max_duration_seconds=3600, max_step_attempts=10),
        )
    # Estimated total cost exceeds budget and is rejected before plan persistence.
    assert store.list_plans() == ()


def test_failure_creates_learning_trigger_only(tmp_path):
    evolution = FakeEvolution()
    orchestrator, store, _ = make_orchestrator(tmp_path, evolution=evolution)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id, operations=("fail",))
    orchestrator.decide(plan.mission_id, approved=True, principal="operator", channel="test", reason="Bounded failure-path test.")
    result = asyncio.run(orchestrator.run(plan.mission_id, principal="operator"))
    assert result.status == MissionStatus.FAILED
    assert len(evolution.triggers) == 1
    assert evolution.triggers[0].metadata["authority"] == "learning-trigger-only"
    assert store.current_status(plan.mission_id) == MissionStatus.FAILED


def test_claimed_realized_verified_value_are_separate(tmp_path):
    orchestrator, _, _ = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    claimed = orchestrator.record_value_evidence(
        mission_id=plan.mission_id, kind=MissionValueKind.CLAIMED,
        description="Estimated customer value", source="mission-analysis", amount_usd=500.0,
    )
    realized = orchestrator.record_value_evidence(
        mission_id=plan.mission_id, kind=MissionValueKind.REALIZED,
        description="Customer payment receipt", source="payment-provider", amount_usd=100.0,
        external_reference="receipt://payment-1",
    )
    with pytest.raises(MissionBlocked, match="trusted"):
        orchestrator.record_value_evidence(
            mission_id=plan.mission_id, kind=MissionValueKind.VERIFIED,
            description="Untrusted verification", source="model", amount_usd=100.0,
            external_reference="receipt://payment-1", related_evidence_id=realized.evidence_id, verified_by="model",
        )
    verified = orchestrator.record_value_evidence(
        mission_id=plan.mission_id, kind=MissionValueKind.VERIFIED,
        description="Founder checked external payment receipt", source="founder-review", amount_usd=100.0,
        external_reference="receipt://payment-1", related_evidence_id=realized.evidence_id, verified_by="founder",
    )
    outcome = asyncio.run(orchestrator.finalize(
        plan.mission_id, achieved=True, summary="Bounded experiment produced one verified payment.",
        lessons=("Validate demand before scaling.",), principal="founder",
    ))
    assert claimed.evidence_id != realized.evidence_id != verified.evidence_id
    assert outcome.claimed_value_usd == 500.0
    assert outcome.realized_revenue_usd == 100.0
    assert outcome.verified_revenue_usd == 100.0
    assert outcome.state.value == "verified"


def test_mission_ledger_is_append_only(tmp_path):
    orchestrator, store, _ = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE mission_plans SET lane='internal-maintenance' WHERE mission_id=?", (plan.mission_id,))


def test_outcome_requires_trusted_principal_terminal_state_and_single_finalize(tmp_path):
    orchestrator, _, _ = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    with pytest.raises(MissionBlocked, match="terminal execution state"):
        asyncio.run(orchestrator.finalize(
            plan.mission_id, achieved=False, summary="Premature outcome.", lessons=(), principal="founder",
        ))
    asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    with pytest.raises(MissionBlocked, match="trusted"):
        asyncio.run(orchestrator.finalize(
            plan.mission_id, achieved=True, summary="Model claims completion.", lessons=(), principal="model",
        ))
    outcome = asyncio.run(orchestrator.finalize(
        plan.mission_id, achieved=True, summary="Founder reviewed the completed mission.",
        lessons=("Keep experiments bounded.",), principal="founder",
    ))
    assert outcome.state == MissionOutcomeState.NO_VALUE
    with pytest.raises(MissionBlocked, match="already finalized"):
        asyncio.run(orchestrator.finalize(
            plan.mission_id, achieved=True, summary="Duplicate finalization.", lessons=(), principal="founder",
        ))


def test_external_supporting_evidence_requires_reference_and_nonempty_source(tmp_path):
    orchestrator, _, _ = make_orchestrator(tmp_path)
    brief = make_brief(
        orchestrator,
        evidence_items=(
            OpportunityEvidence(source="", independent_source_id="", statement="Missing source", stance=OpportunityEvidenceStance.SUPPORTS),
            OpportunityEvidence(source="market-b", independent_source_id="market-b", statement="Missing URL", stance=OpportunityEvidenceStance.SUPPORTS),
        ),
    )
    assert brief.independent_support_count == 1
    blockers = " ".join(brief.blockers)
    assert "requires source and statement" in blockers
    assert "requires an external reference" in blockers
