"""CognitivePlanner — bounded PLAN + one-time GOVERN layer for the Aether Cognitive Executive.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-3): the plan step turns a
CognitiveDirective (WORK-2) into a canonical mission plan via MissionOrchestrator
(intake_opportunity -> create_plan), and govern() performs exactly ONE
constitutional approval at the start (decide approved=True, principal="founder").
There is no per-step approval in the loop.

Gate 6 (MISSION-PCP-005 WORK-2): _build_multi_steps sets mission_principal_id /
mission_execution_profile PER STEP from the step spec (falling back to the
directive for backward compat), honouring the WORK-1 per-step principal contract.
plan_from_directive also fail-closes on a step that resolves to an empty
effective principal before the plan is built. The artifact chain
(relevant_artifacts / relevant_evidence) is unchanged.

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
from aether.executive.cognitive_reasoner import CognitiveDirective, CognitiveStepSpec
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
    """Plans a bounded cognitive mission from a directive and governs it once.

    plan_from_directive is fail-closed: an invalid directive (validate() reports
    blockers) raises ValueError with the directive's blockers. A multi-step
    directive (steps non-empty, MISSION-PCP-004) is decomposed into N canonical
    MissionSteps with a linear depends_on chain and per-step canonical metadata;
    step N+1 carries `relevant_artifacts` referencing step N's expected artifact
    so the deliverable of step N becomes the evidence / input context of step
    N+1 (Gate 5 acceptance item 3). A single-step directive keeps the legacy
    one-step plan shape.

    Gate 6 (PCP-005): each step's mission_principal_id / mission_execution_profile
    is resolved from the step spec (falling back to the directive), so a
    reasoner can assign a DIFFERENT principal per step.

    govern() is a one-time invariant per mission — a second call always raises
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

        # Gate 6 (G6-A): plan-time fail-closed check — before building the plan,
        # every step must resolve to a non-empty effective principal. A step
        # whose spec.principal_id is None AND whose directive.principal_id is
        # empty is a blocker. The legacy single-step path (steps == ()) and the
        # legacy multi-step fallback (directive principal inherited) are unchanged.
        if directive.steps:
            for spec in directive.steps:
                if not (spec.principal_id or directive.principal_id):
                    blockers.append(f"step {spec.step_id} has no effective principal")

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

        steps = (
            self._build_multi_steps(directive)
            if directive.steps
            else (self._build_legacy_step(directive),)
        )
        step_count = len(steps)
        plan = self._orchestrator.create_plan(
            brief_id=brief.brief_id,
            objective=directive.objective,
            northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
            northstar_principle_ids=("SP1", "SP5"),
            strategy_tags=("business_experimentation",),
            steps=steps,
            budget=MissionBudget(
                # Red-team R-PCP004-2 (WORK-4): a multi-step plan's cost budget must
                # cover the estimated cost of ALL steps (1.0 per step); a small
                # directive budget must not make an accepted plan stop at step 1.
                max_cost_usd=max(directive.budget_usd, float(step_count)),
                # Red-team R-PCP004-1 (WORK-4): the execution duration budget scales
                # with the step count so a bounded multi-step live run (each step
                # waits on its pane with a bounded timeout) is not stopped mid-loop
                # by the 600s single-step default.
                max_duration_seconds=600 * step_count,
                max_step_attempts=max(directive.max_steps, step_count),
            ),
            stop_conditions=directive.stop_conditions,
        )
        self._directives[plan.mission_id] = directive
        return plan

    def _build_legacy_step(self, directive: CognitiveDirective) -> MissionStep:
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
        return MissionStep(
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

    def _build_multi_steps(
        self, directive: CognitiveDirective
    ) -> tuple[MissionStep, ...]:
        """Decompose a multi-step directive into N canonical MissionSteps.

        Each spec becomes a MissionStep with its own canonical work_id /
        expected_artifact and a linear depends_on chain. Step N+1 carries
        `relevant_artifacts` = [step N expected artifact] and `relevant_evidence`
        = [step N work_id] so APCB's prompt factory forwards step N's deliverable
        as the input context for step N+1 (Gate 5 acceptance item 3).

        Gate 6 (PCP-005): mission_principal_id / mission_execution_profile are
        resolved PER STEP from the step spec (falling back to the directive), so
        a reasoner can assign a DIFFERENT principal per step. When a spec has no
        per-step overrides, the metadata is byte-for-byte identical to legacy.
        """
        specs = directive.steps
        artifacts_by_id = {spec.step_id: spec.expected_artifact for spec in specs}
        work_ids_by_id = {spec.step_id: spec.work_id for spec in specs}
        ordered: list[MissionStep] = []
        for spec in specs:
            prior_artifacts: list[str] = []
            prior_evidence: list[str] = []
            for dep in spec.depends_on:
                prior_artifact = artifacts_by_id.get(dep)
                if prior_artifact:
                    prior_artifacts.append(prior_artifact)
                prior_work = work_ids_by_id.get(dep)
                if prior_work:
                    prior_evidence.append(prior_work)

            # Gate 6 (G6-A): effective per-step principal/profile; fall back to the
            # directive for backward compat (legacy -> byte-for-byte identical).
            principal = spec.principal_id or directive.principal_id
            profile = spec.execution_profile or directive.execution_profile
            # G6-B: a step with an EXPLICIT per-step principal must not inherit the
            # directive-level capabilities (which belong to the directive's principal).
            # Leave them empty so the canonical mapper derives the step's required
            # capabilities from that principal's own registry entry.
            step_capabilities = (
                () if spec.principal_id else list(directive.capabilities)
            )

            metadata: dict[str, Any] = {
                MISSION_PRINCIPAL_ID: principal,
                MISSION_EXECUTION_PROFILE: profile,
                MISSION_WORKSPACE_ID: directive.workspace_id,
                MISSION_CAPABILITIES: step_capabilities,
                MISSION_EXPECTED_ARTIFACT: spec.expected_artifact,
                MISSION_WORK_ID: spec.work_id,
                "objective": spec.objective,
                "constraints": list(directive.stop_conditions),
                "acceptance_criteria": [*spec.acceptance],
            }
            if prior_artifacts:
                # Gate 5 acceptance item 3: step N artifact -> step N+1 context.
                metadata["relevant_artifacts"] = prior_artifacts
                metadata["relevant_evidence"] = prior_evidence
            ordered.append(
                MissionStep(
                    step_id=spec.step_id,
                    title=f"Execute {spec.step_id} ({spec.work_id})",
                    action=ActionProposal(
                        target=ActionTarget.RUNTIME,
                        operation="implement",
                        required_scopes=(ActionScope.EXECUTE,),
                        reason=f"Run bounded cognitive step {spec.step_id}.",
                        risk=ActionRisk.LOW,
                        reversible=True,
                        metadata=metadata,
                    ),
                    success_criteria=spec.acceptance
                    or (f"{spec.expected_artifact} exists and is non-empty",),
                    depends_on=spec.depends_on,
                    max_attempts=1,
                    estimated_cost_usd=1.0,
                )
            )
        return tuple(ordered)

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
