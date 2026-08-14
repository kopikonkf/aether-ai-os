"""CognitivePlanner — bounded PLAN + one-time GOVERN layer for the Aether Cognitive Executive.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-3): the plan step turns a
CognitiveDirective (WORK-2) into a canonical mission plan via MissionOrchestrator
(intake_opportunity -> create_plan), and govern() performs exactly ONE
constitutional approval at the start (decide approved=True, principal="founder").
There is no per-step approval in the loop.

NON-ACTIVATION: planning and governing never execute a mission step; they only
write the plan + the single decision into the canonical store.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.contracts.missions import (
    MissionBudget,
    MissionDecision,
    MissionLane,
    MissionPlan,
    MissionRisk,
    MissionStep,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.executive.cognitive_reasoner import CognitiveDirective
from aether.missions.canonical_mapper import (
    MISSION_CAPABILITIES,
    MISSION_EXECUTION_PROFILE,
    MISSION_EXPECTED_ARTIFACT,
    MISSION_PRINCIPAL_ID,
    MISSION_WORK_ID,
    MISSION_WORKSPACE_ID,
)

if TYPE_CHECKING:
    from aether.missions.orchestrator import MissionOrchestrator

WORK_ID = "WORK-PCP-003"
_STEP_ID = "step-1"


class DuplicateGovernanceError(RuntimeError):
    """Raised when govern() is called more than once for the same mission."""


class CognitivePlanner:
    """Plans a single bounded cognitive step from a directive and governs it once.

    plan_from_directive is fail-closed: an invalid directive (validate() reports
    blockers) raises ValueError with the directive's blockers. govern() is a
    one-time invariant per mission — a second call always raises
    DuplicateGovernanceError (programmer error), even if the store already holds
    a decision. A store-level pre-existing decision is otherwise honoured
    idempotently by orchestrator.decide().
    """

    def __init__(self, orchestrator: "MissionOrchestrator") -> None:
        self._orchestrator = orchestrator
        self._governed: set[str] = set()
        self._directives: dict[str, CognitiveDirective] = {}

    # ------------------------------------------------------------------ #
    # Plan                                                               #
    # ------------------------------------------------------------------ #
    def plan_from_directive(self, directive: CognitiveDirective) -> MissionPlan:
        blockers = directive.validate()
        if blockers:
            raise ValueError("invalid directive: " + ", ".join(blockers))

        brief = self._orchestrator.intake_opportunity(
            title="Bounded cognitive executive step",
            lane=MissionLane.EXTERNAL_VALUE,
            problem_statement="A single bounded cognitive step to advance the Aether executive loop.",
            beneficiary="Aether cognitive executive",
            value_proposition="Produce one deterministic deliverable while staying bounded and reversible.",
            probability_success=0.5,
            upside_usd=10.0,
            estimated_cost_usd=1.0,
            estimated_duration_hours=0.5,
            revenue_hypothesis="One accepted deliverable advances the closed-loop proof value.",
            assumptions=("The step is small, reversible, and evidence-first.",),
            evidence=(
                OpportunityEvidence(
                    source="evidence-a",
                    independent_source_id="evidence-a",
                    statement="Deterministic supporting evidence for the bounded step.",
                    stance=OpportunityEvidenceStance.SUPPORTS,
                    external_reference="https://evidence.invalid/a",
                ),
                OpportunityEvidence(
                    source="evidence-b",
                    independent_source_id="evidence-b",
                    statement="Second independent supporting evidence.",
                    stance=OpportunityEvidenceStance.SUPPORTS,
                    external_reference="https://evidence.invalid/b",
                ),
            ),
            risk=MissionRisk.LOW,
            confidence=0.6,
        )

        metadata: dict[str, Any] = {
            MISSION_PRINCIPAL_ID: directive.principal_id,
            MISSION_EXECUTION_PROFILE: directive.execution_profile,
            MISSION_WORKSPACE_ID: directive.workspace_id,
            MISSION_CAPABILITIES: list(directive.capabilities),
            MISSION_EXPECTED_ARTIFACT: directive.expected_artifact,
            MISSION_WORK_ID: WORK_ID,
            "objective": directive.objective,
            "constraints": list(directive.stop_conditions),
            "acceptance_criteria": [f"produce {directive.expected_artifact}"],
        }
        step = MissionStep(
            step_id=_STEP_ID,
            title="Execute bounded cognitive step",
            action=ActionProposal(
                target=ActionTarget.RUNTIME,
                operation="implement",
                required_scopes=(ActionScope.EXECUTE,),
                reason="Run bounded cognitive step.",
                risk=ActionRisk.LOW,
                reversible=True,
                metadata=metadata,
            ),
            success_criteria=(f"{directive.expected_artifact} exists and is non-empty",),
            depends_on=(),
            max_attempts=1,
            estimated_cost_usd=1.0,
        )
        plan = self._orchestrator.create_plan(
            brief_id=brief.brief_id,
            objective=directive.objective,
            northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
            northstar_principle_ids=("SP1", "SP5"),
            strategy_tags=("business_experimentation",),
            steps=(step,),
            budget=MissionBudget(
                max_cost_usd=directive.budget_usd,
                max_duration_seconds=600,
                max_step_attempts=directive.max_steps,
            ),
            stop_conditions=directive.stop_conditions,
        )
        self._directives[plan.mission_id] = directive
        return plan

    # ------------------------------------------------------------------ #
    # Govern (one-time constitutional approval)                           #
    # ------------------------------------------------------------------ #
    def govern(self, plan: MissionPlan) -> MissionDecision:
        mission_id = plan.mission_id
        if mission_id in self._governed:
            raise DuplicateGovernanceError(
                f"mission {mission_id} already governed (one-time invariant)"
            )
        directive = self._directives.get(mission_id)
        rationale = directive.rationale if directive is not None else "Gate 4 constitutional approval"
        decision = self._orchestrator.decide(
            mission_id,
            approved=True,
            principal="founder",
            channel="constitutional",
            reason=rationale or "Gate 4 constitutional approval",
        )
        self._governed.add(mission_id)
        return decision
