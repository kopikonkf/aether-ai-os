"""MISSION-PCP-002 WORK-3 — mission-state observer wire (F-07).

Tests for aether.missions.mission_state_observer:
  - mission_status_to_apcb maps every MissionStatus deterministically.
  - build_mission_state_observer reads the LIVE SQLiteMissionStore so APCB
    dispatch/reconcile honours canonical Aether terminal state.
  - the observer is never allowed to raise (empty id / store error -> unknown).
  - APCBDispatcher wired with the store observer STOPS a work item when the
    mission is terminal (F-07 live, via reconcile).

Deterministic: uses a real SQLiteMissionStore in tmp_path and a mock adapter —
no live herdr, no real dispatch.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from aether.apcb import (
    APCBDispatcher,
    AdapterConformanceStatus,
    BridgeExecutionReceipt,
    ConformanceGate,
    ExecutionReceiptStatus,
    ReceiptStore,
)
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.contracts import (
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    MissionBudget,
    MissionLane,
    MissionRisk,
    MissionStatus,
    MissionStep,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.events import EventBus
from aether.missions import MissionOrchestrator, SQLiteMissionStore
from aether.missions.mission_state_observer import (
    build_mission_state_observer,
    mission_status_to_apcb,
)

ALL_MISSION_STATUSES = list(MissionStatus)

EXPECTED_APCB_MAP = {
    MissionStatus.DRAFT: "draft",
    MissionStatus.REVIEW_REQUIRED: "review-required",
    MissionStatus.APPROVED: "approved",
    MissionStatus.REJECTED: "rejected",
    MissionStatus.RUNNING: "running",
    MissionStatus.WAITING_APPROVAL: "waiting-approval",
    MissionStatus.PAUSED: "paused",
    MissionStatus.COMPLETED: "completed",
    MissionStatus.FAILED: "failed",
    MissionStatus.CANCELLED: "cancelled",
    MissionStatus.STOPPED: "stopped",
}


# ---------------------------------------------------------------------------
# MissionStatus -> APCB string mapping
# ---------------------------------------------------------------------------
def test_mission_status_mapping_semua():
    for status in ALL_MISSION_STATUSES:
        assert mission_status_to_apcb(status) == EXPECTED_APCB_MAP[status]


def test_mission_status_mapping_none_is_unknown():
    assert mission_status_to_apcb(None) == "unknown"


# ---------------------------------------------------------------------------
# Store-backed observer
# ---------------------------------------------------------------------------
class CompletedExecutor:
    async def execute(self, proposal: ActionProposal):
        return type(
            "R",
            (),
            {
                "ok": True,
                "status": "completed",
                "output": "ok",
                "error": None,
                "failure_fingerprint": None,
                "metadata": {},
            },
        )()

    async def approval_result(self, approval_id: str):
        return None


def make_orchestrator(tmp_path: Path):
    store = SQLiteMissionStore(tmp_path / "missions.sqlite3")
    executor = CompletedExecutor()
    orchestrator = MissionOrchestrator(
        store,
        executor,
        event_bus=EventBus(tmp_path / "events.jsonl"),
        maximum_steps_per_run=5,
    )
    return orchestrator, store


def evidence(source: str) -> OpportunityEvidence:
    return OpportunityEvidence(
        source=source,
        independent_source_id=source,
        statement=f"Evidence from {source}",
        stance=OpportunityEvidenceStance.SUPPORTS,
        external_reference=f"https://evidence.invalid/{source}",
    )


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


def make_plan(orchestrator: MissionOrchestrator, brief_id: str):
    return orchestrator.create_plan(
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
                max_attempts=1,
                estimated_cost_usd=1.0,
            ),
        ),
        budget=MissionBudget(max_cost_usd=10.0, max_duration_seconds=3600, max_step_attempts=10),
        stop_conditions=("Stop when budget is exhausted.",),
    )


def test_observer_reads_store(tmp_path: Path):
    orchestrator, store = make_orchestrator(tmp_path)
    observer = build_mission_state_observer(store)

    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)

    # Freshly created mission is REVIEW_REQUIRED (plan proposed, not yet decided).
    assert store.current_status(plan.mission_id) == MissionStatus.REVIEW_REQUIRED
    assert observer(plan.mission_id) == "review-required"

    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    assert store.current_status(plan.mission_id) == MissionStatus.COMPLETED
    assert observer(plan.mission_id) == "completed"


def test_observer_unknown_on_empty_mission_id(tmp_path: Path):
    orchestrator, store = make_orchestrator(tmp_path)
    observer = build_mission_state_observer(store)
    assert observer("") == "unknown"


def test_observer_never_raises_on_unknown_mission(tmp_path: Path):
    orchestrator, store = make_orchestrator(tmp_path)
    observer = build_mission_state_observer(store)
    assert observer("mission-does-not-exist") == "unknown"


# ---------------------------------------------------------------------------
# F-07: APCB dispatcher wired to the store observer stops on terminal mission
# ---------------------------------------------------------------------------
class MockAdapter:
    def __init__(self):
        self.agent_ref = "herdr://pane/w7:p3"

    def ensure_agent(self, workspace_ref, principal_id, herdr_agent_kind=None):
        return self.agent_ref

    def prompt_agent(self, agent_ref, task_context):
        return f"{agent_ref}/prompt"

    def wait_agent(self, agent_ref, timeout_seconds):
        return _Obs("done", is_terminal=True)

    def read_agent(self, agent_ref, limit_bytes=8192):
        return "[mock] output"

    def observe_agent(self, agent_ref):
        return _Obs("done", is_terminal=True)

    def recover_agent(self, agent_ref):
        return _Obs("done", is_terminal=True)


class _Obs:
    def __init__(self, status, is_terminal=False):
        self.agent_ref = ""
        self.status = status
        self.is_terminal = is_terminal


def make_dispatcher_with_observer(profiles, receipts, adapter, observer):
    gate = ConformanceGate(profiles, probe=lambda kind: AdapterConformanceStatus.HEALTHY)
    return APCBDispatcher(
        profiles=profiles,
        receipts=receipts,
        conformance_gate=gate,
        adapter=adapter,
        aether_state_observer=observer,
        wait_timeout_seconds=0.5,
    )


def ready_work(mission_id: str = "MISSION-PCP-002") -> WorkItemView:
    return WorkItemView(
        work_id="WORK-PCP-002",
        mission_id=mission_id,
        principal_id="qwen",
        required_capabilities=("coding",),
        workspace_id="workspace://default",
        authorized=True,
        execution_ready=True,
        awaiting_approval=False,
        attempt_number=1,
        execution_profile="herdr:cline",
        metadata={},
    )


def test_dispatcher_stops_when_mission_terminal_via_observer(tmp_path: Path):
    # Mission already COMPLETED in the live store -> observer returns "completed"
    # -> APCB reconcile must STOP the work item (F-07), never promote.
    orchestrator, store = make_orchestrator(tmp_path)
    brief = make_brief(orchestrator)
    plan = make_plan(orchestrator, brief.brief_id)
    orchestrator.decide(plan.mission_id, approved=True, principal="founder", channel="test", reason="Approve bounded experiment.")
    asyncio.run(orchestrator.run(plan.mission_id, principal="founder"))
    assert store.current_status(plan.mission_id) == MissionStatus.COMPLETED

    observer = build_mission_state_observer(store)
    receipts = ReceiptStore(tmp_path / "receipts.jsonl")
    receipts.persist(
        BridgeExecutionReceipt(
            work_id="WORK-PCP-002",
            attempt_number=1,
            principal_id="qwen",
            mission_id=plan.mission_id,
            state=ExecutionReceiptStatus.PROMPTED,
            herdr_execution_ref="herdr://pane/w7:p3",
            observed_at="2026-08-13T00:00:00Z",
        )
    )
    dispatcher = make_dispatcher_with_observer(
        PrincipalRuntimeProfiles(), receipts, MockAdapter(), observer
    )
    decision = dispatcher.reconcile(ready_work(plan.mission_id))
    assert decision.status == "terminal"
    assert decision.terminal_outcome == "stopped"
    assert f"aether mission state=completed" in " ".join(decision.diagnostic)
