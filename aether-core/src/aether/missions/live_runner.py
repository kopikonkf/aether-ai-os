"""Live cognitive mission runner — single-principal Slice C assembly.

MISSION-PCP-002 WORK-5: assemble the full cognitive single-principal chain:

    MissionOrchestrator -> ApcbMissionActionExecutor -> APCBDispatcher
        -> canonical work_mapper -> mission-state observer -> artifact_verify

This is the acceptance path: Aether produces a canonical mission step, APCB
dispatches to a principal worker, the worker writes the deliverable artifact,
and reconcile + artifact authority produce evidence in the mission store. No
Founder relay, no AI-to-AI chat bus.

Design notes:
  - The runner is a COMPOSER only. It does not modify MissionOrchestrator,
    APCBDispatcher, ApcbMissionActionExecutor, or the canonical mapper. Every
    component is assembled here.
  - No live Herdr object is created in __init__ (tests inject a mock adapter);
    the live adapter is passed to build_dispatcher / run_cognitive_mission.
  - validate_pane_map_unique is deliberately NOT called here — the live caller
    owns that startup gate so deterministic tests stay free.
  - The default principal for PCP-002 is chatgpt (herdr:opencode, w7:p3),
    single principal. Workspace is a mission temp directory that must exist on
    disk for artifact_verify to resolve the deliverable.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from aether.apcb.conformance import ConformanceGate
from aether.apcb.dispatcher import APCBDispatcher
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles, load_principal_profiles
from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget, ActionResult
from aether.contracts.missions import (
    ExpectedValueBrief,
    MissionActionExecutor,
    MissionBudget,
    MissionExecution,
    MissionLane,
    MissionPlan,
    MissionRisk,
    MissionStep,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.events import EventBus
from aether.missions import MissionOrchestrator, SQLiteMissionStore
from aether.missions.apcb_executor import ApcbMissionActionExecutor
from aether.missions.canonical_mapper import (
    MISSION_EXPECTED_ARTIFACT,
    build_canonical_work_mapper,
    build_mission_artifact_verify,
)
from aether.missions.mission_state_observer import build_mission_state_observer

# Canonical metadata keys the runner sets on the mission step action.
_MISSION_PRINCIPAL_ID = "mission_principal_id"
_MISSION_EXECUTION_PROFILE = "mission_execution_profile"
_MISSION_WORKSPACE_ID = "mission_workspace_id"
_MISSION_CAPABILITIES = "mission_capabilities"
_MISSION_WORK_ID = "mission_work_id"


def _build_workspace_verify() -> Callable[[str], bool]:
    """Workspace-binding verifier: a real directory must exist on disk.

    URI-style or empty workspace refs are passed through (no local binding
    gate), matching the CLI behaviour.
    """

    def verify(ws: str) -> bool:
        if not ws or "://" in ws:
            return True
        try:
            return Path(ws).is_dir()
        except OSError:
            return False

    return verify


def _build_artifact_verify() -> Callable[[WorkItemView], bool]:
    """Mission-level ADR-0057 verifier keyed off work.metadata.

    Reads mission_expected_artifact from the work item metadata and delegates
    to build_mission_artifact_verify (canonical envelope check). A work item
    with no expected artifact passes (no artifact gate for that step).
    """

    def verify(work: WorkItemView) -> bool:
        expected = (work.metadata or {}).get(MISSION_EXPECTED_ARTIFACT)
        verifier = build_mission_artifact_verify(expected)
        if verifier is None:
            return True
        return verifier(work)

    return verify


class _ArtifactGatedExecutor:
    """Wrap ApcbMissionActionExecutor with the live artifact-acceptance rule.

    ADR-0057: a "completed" terminal REQUIRES the deliverable artifact. The
    APCB dispatcher already downgrades a done-but-missing-artifact observation
    to completed_without_artifact; this wrapper translates that into a failed
    mission step (ok=False) so the orchestrator never records a completed
    attempt without accepted evidence. Pure composition — nothing below is
    modified.
    """

    def __init__(self, inner: ApcbMissionActionExecutor) -> None:
        self._inner = inner
        self.work_mapper = inner.work_mapper
        self.mission_state_observer = inner.mission_state_observer
        self.artifact_verify = inner.artifact_verify

    async def execute(self, proposal: ActionProposal) -> ActionResult:
        result = await self._inner.execute(proposal)
        if result.status == "completed_without_artifact":
            return ActionResult(
                action_id=result.action_id,
                ok=False,
                status="failed",
                error="deliverable artifact missing in workspace (ADR-0057 artifact authority)",
                metadata={**dict(result.metadata), "artifact_missing": True},
            )
        return result

    async def approval_result(self, approval_id: str) -> ActionResult | None:
        return await self._inner.approval_result(approval_id)


class MissionCognitiveRunner:
    """Compose the cognitive single-principal mission chain over APCB.

    All paths are stored; heavy objects (store, profiles, dispatcher, executor)
    are built lazily so tests can inject deterministic mocks.
    """

    def __init__(
        self,
        store_path: str | Path,
        receipts_path: str | Path,
        registry_path: str | Path | None = None,
        pane_map_path: str | Path | None = None,
        workspace_override: str | Path | None = None,
        events_path: str | Path | None = None,
        wait_timeout_seconds: float = 300.0,
    ) -> None:
        self.store_path = Path(store_path)
        self.receipts_path = Path(receipts_path)
        self.registry_path = Path(registry_path) if registry_path else None
        self.pane_map_path = Path(pane_map_path) if pane_map_path else None
        self.workspace_override = str(workspace_override) if workspace_override else None
        self.events_path = events_path or self.store_path.with_name(
            f"{self.store_path.stem}.events.jsonl"
        )
        self.wait_timeout_seconds = wait_timeout_seconds
        self._store: SQLiteMissionStore | None = None
        self._profiles: PrincipalRuntimeProfiles | None = None

    # ------------------------------------------------------------------ #
    # Lazy dependencies                                                    #
    # ------------------------------------------------------------------ #
    @property
    def store(self) -> SQLiteMissionStore:
        if self._store is None:
            self._store = SQLiteMissionStore(self.store_path)
        return self._store

    def _load_profiles(self) -> PrincipalRuntimeProfiles:
        if self._profiles is None:
            self._profiles = load_principal_profiles(self.registry_path)
        return self._profiles

    # ------------------------------------------------------------------ #
    # Assembly                                                            #
    # ------------------------------------------------------------------ #
    def build_dispatcher(self, adapter) -> APCBDispatcher:
        """Assemble a fully wired APCBDispatcher for a given execution adapter.

        Wires ConformanceGate (adapter probe), ReceiptStore, the canonical
        mission-state observer, a workspace-binding verifier and the
        mission-level artifact verifier. If a pane map path was supplied it is
        exposed via APCB_HERDR_PANE_MAP so the adapter's default pane resolver
        can bind principals to panes.
        """
        if self.pane_map_path is not None:
            os.environ["APCB_HERDR_PANE_MAP"] = str(self.pane_map_path)
        profiles = self._load_profiles()
        gate = ConformanceGate(profiles, probe=adapter.detect_adapter)
        return APCBDispatcher(
            profiles=profiles,
            receipts=ReceiptStore(self.receipts_path),
            conformance_gate=gate,
            adapter=adapter,
            aether_state_observer=build_mission_state_observer(self.store),
            workspace_verify=_build_workspace_verify(),
            artifact_verify=_build_artifact_verify(),
            wait_timeout_seconds=self.wait_timeout_seconds,
        )

    def build_executor(self, adapter) -> MissionActionExecutor:
        """Assemble the mission action executor over a wired dispatcher.

        Uses the canonical governed work_mapper (build_canonical_work_mapper)
        and carries the mission-state observer + artifact verifier so the live
        runner / orchestrator honours LIVE mission state and artifact authority.
        The returned executor is wrapped with the artifact-acceptance rule:
        a done-without-artifact observation is a failed step, never a completed
        attempt (ADR-0057).
        """
        dispatcher = self.build_dispatcher(adapter)
        inner = ApcbMissionActionExecutor(
            dispatcher,
            None,
            profiles=self._load_profiles(),
            mission_state_observer=build_mission_state_observer(self.store),
            artifact_verify=_build_artifact_verify(),
        )
        return _ArtifactGatedExecutor(inner)

    # ------------------------------------------------------------------ #
    # Cognitive mission helper                                            #
    # ------------------------------------------------------------------ #
    def _default_workspace(self) -> str:
        if self.workspace_override:
            return self.workspace_override
        base = self.store_path.parent / "mission-ws"
        return str(base)

    def _make_brief(self, orchestrator: MissionOrchestrator) -> ExpectedValueBrief:
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
            evidence=(
                OpportunityEvidence(
                    source="ev-a",
                    independent_source_id="ev-a",
                    statement="Evidence from ev-a",
                    stance=OpportunityEvidenceStance.SUPPORTS,
                    external_reference="https://evidence.invalid/ev-a",
                ),
                OpportunityEvidence(
                    source="ev-b",
                    independent_source_id="ev-b",
                    statement="Evidence from ev-b",
                    stance=OpportunityEvidenceStance.SUPPORTS,
                    external_reference="https://evidence.invalid/ev-b",
                ),
            ),
            risk=MissionRisk.LOW,
            confidence=0.6,
        )

    def _make_plan(
        self,
        orchestrator: MissionOrchestrator,
        brief_id: str,
        *,
        workspace: str,
        principal_id: str,
        execution_profile: str,
        expected_artifact: str,
        capabilities: tuple[str, ...],
        work_id: str | None,
        objective: str,
        step_title: str,
        success_criteria: tuple[str, ...],
    ) -> MissionPlan:
        metadata: dict[str, Any] = {
            _MISSION_PRINCIPAL_ID: principal_id,
            _MISSION_WORKSPACE_ID: workspace,
            _MISSION_EXECUTION_PROFILE: execution_profile,
            _MISSION_CAPABILITIES: list(capabilities),
            MISSION_EXPECTED_ARTIFACT: expected_artifact,
        }
        if work_id:
            metadata[_MISSION_WORK_ID] = work_id
        return orchestrator.create_plan(
            brief_id=brief_id,
            objective=objective,
            northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
            northstar_principle_ids=("SP1", "SP5"),
            strategy_tags=("business_experimentation",),
            steps=(
                MissionStep(
                    step_id="step-1",
                    title=step_title,
                    action=ActionProposal(
                        target=ActionTarget.RUNTIME,
                        operation="implement",
                        required_scopes=(ActionScope.EXECUTE,),
                        reason="Run bounded cognitive step.",
                        risk=ActionRisk.LOW,
                        reversible=True,
                        metadata=metadata,
                    ),
                    success_criteria=success_criteria,
                    depends_on=(),
                    max_attempts=1,
                    estimated_cost_usd=1.0,
                ),
            ),
            budget=MissionBudget(max_cost_usd=10.0, max_duration_seconds=3600, max_step_attempts=10),
            stop_conditions=("Stop when budget is exhausted.",),
        )

    async def run_cognitive_mission(
        self,
        adapter,
        *,
        workspace: str | None = None,
        principal_id: str = "chatgpt",
        execution_profile: str = "herdr:opencode",
        expected_artifact: str = "WORK-PCP-002.md",
        capabilities: tuple[str, ...] = ("systems_integration",),
        work_id: str | None = "WORK-PCP-002",
        objective: str = "Produce the canonical PCP-002 deliverable artifact.",
        step_title: str = "Deliver bounded step artifact",
        success_criteria: tuple[str, ...] | None = None,
    ) -> MissionExecution:
        """Run one bounded cognitive mission to completion via APCB.

        Creates the workspace directory, assembles orchestrator + executor +
        dispatcher, intakes a small opportunity, proposes a single-step plan
        whose action carries the canonical mission metadata, approves it, and
        runs it. Returns the MissionExecution (caller reads the store for
        attempts/evidence).
        """
        ws = workspace or self._default_workspace()
        Path(ws).mkdir(parents=True, exist_ok=True)

        criteria = success_criteria or (f"{expected_artifact} present in workspace with matching envelope.",)
        executor = self.build_executor(adapter)
        orchestrator = MissionOrchestrator(
            self.store,
            executor,
            event_bus=EventBus(self.events_path),
            maximum_steps_per_run=5,
        )
        brief = self._make_brief(orchestrator)
        plan = self._make_plan(
            orchestrator,
            brief.brief_id,
            workspace=ws,
            principal_id=principal_id,
            execution_profile=execution_profile,
            expected_artifact=expected_artifact,
            capabilities=capabilities,
            work_id=work_id,
            objective=objective,
            step_title=step_title,
            success_criteria=criteria,
        )
        orchestrator.decide(
            plan.mission_id,
            approved=True,
            principal="founder",
            channel="test",
            reason="Approve bounded cognitive experiment.",
        )
        return await orchestrator.run(plan.mission_id, principal="founder")
