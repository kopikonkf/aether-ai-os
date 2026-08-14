"""MISSION-PCP-003 WORK-3 — CognitivePlanner one-time governance tests.

Tests for aether.executive.cognitive_planner:
  - plan_from_directive creates a valid 1-step canonical mission plan carrying
    the directive's principal/profile/artifact;
  - action metadata carries objective/constraints/acceptance_criteria;
  - govern() approves exactly once (store decision APPROVED + status APPROVED);
  - a second govern() on the same plan raises DuplicateGovernanceError;
  - a store decision created outside the planner is honoured idempotently;
  - decision.reason carries the directive's rationale;
  - plan_from_directive is fail-closed on an invalid directive.

Deterministic: real SQLiteMissionStore in tmp_path + a dummy executor that is
never invoked — no live dispatch, no herdr.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aether.contracts.missions import MissionDecisionType, MissionStatus
from aether.executive.cognitive_planner import CognitivePlanner, DuplicateGovernanceError
from aether.executive.cognitive_reasoner import CognitiveDirective, CognitiveStepSpec
from aether.missions.orchestrator import MissionOrchestrator
from aether.missions.store import SQLiteMissionStore


class DummyExecutor:
    async def execute(self, proposal):
        raise AssertionError("planner/govern must never execute a step")

    async def approval_result(self, approval_id):
        raise AssertionError("planner/govern must never query approvals")


def make_planner(tmp_path: Path) -> tuple[CognitivePlanner, MissionOrchestrator, SQLiteMissionStore]:
    store = SQLiteMissionStore(tmp_path / "missions.sqlite3")
    orchestrator = MissionOrchestrator(store, DummyExecutor())
    return CognitivePlanner(orchestrator), orchestrator, store


def valid_directive(**overrides) -> CognitiveDirective:
    fields = {
        "objective": "Address observed Aether state",
        "expected_artifact": "WORK-PCP-003.md",
        "principal_id": "chatgpt",
        "execution_profile": "herdr:opencode",
        "workspace_id": "workspace://pcp-003",
        "capabilities": ("systems_integration",),
        "max_steps": 1,
        "budget_usd": 10.0,
        "stop_conditions": ("stop when budget exhausted",),
        "rationale": "rule-based: deterministic default",
    }
    fields.update(overrides)
    return CognitiveDirective(**fields)


def test_plan_from_directive_creates_valid_plan(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    directive = valid_directive()
    plan = planner.plan_from_directive(directive)
    assert plan.mission_id
    assert len(plan.steps) == 1
    metadata = dict(plan.steps[0].action.metadata)
    assert metadata["mission_principal_id"] == directive.principal_id
    assert metadata["mission_execution_profile"] == directive.execution_profile
    assert metadata["mission_workspace_id"] == directive.workspace_id
    assert metadata["mission_expected_artifact"] == directive.expected_artifact
    assert metadata["mission_work_id"] == "WORK-PCP-003"
    assert plan.budget.max_cost_usd == directive.budget_usd
    assert plan.budget.max_step_attempts == directive.max_steps


def test_plan_metadata_carries_directive(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    directive = valid_directive()
    plan = planner.plan_from_directive(directive)
    metadata = dict(plan.steps[0].action.metadata)
    assert metadata["objective"] == directive.objective
    assert list(metadata["constraints"]) == list(directive.stop_conditions)
    assert metadata["acceptance_criteria"] == ["produce WORK-PCP-003.md"]


def test_govern_approves_once(tmp_path: Path):
    planner, orchestrator, store = make_planner(tmp_path)
    plan = planner.plan_from_directive(valid_directive())
    planner.govern(plan)
    decision = store.get_decision(plan.mission_id)
    assert decision is not None
    assert decision.decision == MissionDecisionType.APPROVE
    assert store.current_status(plan.mission_id) == MissionStatus.APPROVED


def test_govern_duplicate_raises(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    plan = planner.plan_from_directive(valid_directive())
    planner.govern(plan)
    with pytest.raises(DuplicateGovernanceError):
        planner.govern(plan)


def test_govern_idempotent_on_store_decision(tmp_path: Path):
    # A mission decided manually (outside the planner) is honoured: govern()
    # returns the existing decision without raising, because it was never
    # governed by THIS planner instance.
    planner, orchestrator, store = make_planner(tmp_path)
    plan = planner.plan_from_directive(valid_directive())
    orchestrator.decide(
        plan.mission_id,
        approved=True,
        principal="founder",
        channel="test",
        reason="manual pre-existing decision",
    )
    decision = planner.govern(plan)
    assert decision.decision == MissionDecisionType.APPROVE
    assert store.get_decision(plan.mission_id).decision == MissionDecisionType.APPROVE


def test_govern_reason_carries_rationale(tmp_path: Path):
    planner, _, store = make_planner(tmp_path)
    plan = planner.plan_from_directive(valid_directive(rationale="my governance rationale"))
    planner.govern(plan)
    assert "my governance rationale" in store.get_decision(plan.mission_id).reason


def test_plan_from_directive_fail_closed_invalid(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    with pytest.raises(ValueError, match="invalid directive"):
        planner.plan_from_directive(valid_directive(objective=""))


# ---------------------------------------------------------------------------
# MISSION-PCP-004 WORK-2 — multi-step plan (Gate 5 acceptance items 1+3)
# ---------------------------------------------------------------------------
def multi_step_directive(**overrides) -> CognitiveDirective:
    fields = {
        "objective": "Multi-step cognitive mission (3 steps)",
        "expected_artifact": "WORK-PCP-004.md",
        "principal_id": "chatgpt",
        "execution_profile": "herdr:opencode",
        "workspace_id": "workspace://pcp-004",
        "capabilities": ("systems_integration",),
        "max_steps": 3,
        "budget_usd": 10.0,
        "stop_conditions": ("stop when budget exhausted",),
        "rationale": "deterministic multi-step directive",
        "steps": (
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "Deliver step 1 of 3.", "WORK-PCP-004-S1.md", (), ("produce WORK-PCP-004-S1.md",)),
            CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "Deliver step 2 of 3.", "WORK-PCP-004-S2.md", ("step-1",), ("produce WORK-PCP-004-S2.md",)),
            CognitiveStepSpec("step-3", "WORK-PCP-004-S3", "Deliver step 3 of 3.", "WORK-PCP-004-S3.md", ("step-2",), ("produce WORK-PCP-004-S3.md",)),
        ),
    }
    fields.update(overrides)
    return CognitiveDirective(**fields)


def test_plan_from_directive_creates_multi_step_plan(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    directive = multi_step_directive()
    plan = planner.plan_from_directive(directive)
    assert plan.mission_id
    assert len(plan.steps) == 3
    # Linear depends_on chain: step-1 -> step-2 -> step-3.
    assert plan.steps[0].depends_on == ()
    assert plan.steps[1].depends_on == ("step-1",)
    assert plan.steps[2].depends_on == ("step-2",)
    # Per-step canonical metadata: distinct work_id / expected_artifact.
    meta2 = dict(plan.steps[1].action.metadata)
    assert meta2["mission_work_id"] == "WORK-PCP-004-S2"
    assert meta2["mission_expected_artifact"] == "WORK-PCP-004-S2.md"
    assert meta2["mission_principal_id"] == directive.principal_id
    assert meta2["mission_execution_profile"] == directive.execution_profile
    # Budget must cover 3 steps (1 attempt each).
    assert plan.budget.max_step_attempts >= 3
    assert plan.budget.max_cost_usd == directive.budget_usd


def test_plan_artifact_chain_metadata(tmp_path: Path):
    # Gate 5 acceptance item 3: step N+1 carries relevant_artifacts referencing
    # step N's artifact + relevant_evidence referencing step N's work_id, so the
    # APCB prompt factory forwards step N's deliverable as context to step N+1.
    planner, _, _ = make_planner(tmp_path)
    plan = planner.plan_from_directive(multi_step_directive())
    meta1 = dict(plan.steps[0].action.metadata)
    meta2 = dict(plan.steps[1].action.metadata)
    meta3 = dict(plan.steps[2].action.metadata)
    assert "relevant_artifacts" not in meta1  # first step has no input artifact
    assert meta2["relevant_artifacts"] == ["WORK-PCP-004-S1.md"]
    assert meta2["relevant_evidence"] == ["WORK-PCP-004-S1"]
    assert meta3["relevant_artifacts"] == ["WORK-PCP-004-S2.md"]
    assert meta3["relevant_evidence"] == ["WORK-PCP-004-S2"]
    # Acceptance criteria carry each step's own artifact.
    assert meta2["acceptance_criteria"] == ["produce WORK-PCP-004-S2.md"]


def test_plan_multi_step_govern_once(tmp_path: Path):
    planner, _, store = make_planner(tmp_path)
    plan = planner.plan_from_directive(multi_step_directive())
    planner.govern(plan)
    assert store.get_decision(plan.mission_id).decision == MissionDecisionType.APPROVE
    with pytest.raises(DuplicateGovernanceError):
        planner.govern(plan)


def test_plan_multi_step_fail_closed_invalid_chain(tmp_path: Path):
    planner, _, _ = make_planner(tmp_path)
    directive = multi_step_directive(
        steps=(
            CognitiveStepSpec("step-1", "WORK-PCP-004-S1", "s1", "WORK-PCP-004-S1.md", (), ("produce X.md",)),
            CognitiveStepSpec("step-2", "WORK-PCP-004-S2", "s2", "WORK-PCP-004-S2.md", ("step-9",), ("produce Y.md",)),
        )
    )
    with pytest.raises(ValueError, match="invalid directive"):
        planner.plan_from_directive(directive)
