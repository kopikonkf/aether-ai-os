"""CognitiveExecutive — closed-loop driver: execute -> observe -> evaluate -> decide -> next.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-4): the core driver that runs
one bounded cognitive loop END-TO-END without a Founder relay between steps.
Governance happens exactly ONCE at the start (planner.govern), and every
subsequent step proceeds through the canonical store + APCB receipt evidence:

    observe -> plan -> govern-once -> execute -> observe-outcome ->
    evaluate evidence -> decide next (bounded) -> execute next ...

The loop is bounded by min(self.max_steps, directive.max_steps) iterations and
stops on any terminal mission state, so it can never spin indefinitely.
NON-ACTIVATION in tests: the adapter is a deterministic mock; the live Herdr
adapter is injected only by COORD at live smoke time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aether.apcb.eligibility import WorkItemView
from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.missions import (
    MissionBlocked,
    MissionStatus,
    MissionStepStatus,
)
from aether.events import EventBus
from aether.missions.canonical_mapper import (
    MISSION_EXECUTION_PROFILE,
    MISSION_EXPECTED_ARTIFACT,
    MISSION_PRINCIPAL_ID,
    MISSION_WORK_ID,
    MISSION_WORKSPACE_ID,
    build_mission_artifact_verify,
)
from aether.missions.orchestrator import MissionOrchestrator

if TYPE_CHECKING:
    from aether.executive.cognitive_observer import CognitiveObserver
    from aether.executive.cognitive_planner import CognitivePlanner
    from aether.executive.cognitive_reasoner import CognitiveDirective, CognitiveReasoner
    from aether.missions.live_runner import MissionCognitiveRunner

LOG = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {
        MissionStatus.COMPLETED,
        MissionStatus.FAILED,
        MissionStatus.STOPPED,
        MissionStatus.CANCELLED,
        MissionStatus.REJECTED,
    }
)


@dataclass(frozen=True)
class CognitiveLoopResult:
    """Immutable result of one closed cognitive loop run."""

    mission_id: str
    status: str
    steps_executed: tuple[str, ...] = ()
    evidence_evaluations: tuple[dict[str, Any], ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    governance_count: int = 1
    completed: bool = False


class CognitiveExecutive:
    """Run one bounded closed cognitive loop over observer/planner/runner."""

    def __init__(
        self,
        runner: "MissionCognitiveRunner",
        observer: "CognitiveObserver",
        reasoner: "CognitiveReasoner",
        planner: "CognitivePlanner",
        *,
        max_steps: int = 3,
        adapter: Any | None = None,
    ) -> None:
        self._runner = runner
        self._observer = observer
        self._reasoner = reasoner
        self._planner = planner
        self.max_steps = max(1, int(max_steps))
        self._adapter = adapter
        self._orchestrator_inst: MissionOrchestrator | None = None
        self._receipts_inst: ReceiptStore | None = None

    # ------------------------------------------------------------------ #
    # Lazy dependencies (runner owns the canonical store + APCB wiring)    #
    # ------------------------------------------------------------------ #
    def _orchestrator(self) -> MissionOrchestrator:
        if self._orchestrator_inst is None:
            if self._adapter is None:
                raise RuntimeError(
                    "CognitiveExecutive requires an execution adapter (mock for "
                    "deterministic tests; live HerdrExecutionAdapter at smoke time)"
                )
            executor = self._runner.build_executor(self._adapter)
            self._orchestrator_inst = MissionOrchestrator(
                self._runner.store,
                executor,
                event_bus=EventBus(self._runner.events_path),
                maximum_steps_per_run=min(self.max_steps, 5),
            )
        return self._orchestrator_inst

    def _receipts(self) -> ReceiptStore:
        if self._receipts_inst is None:
            self._receipts_inst = ReceiptStore(self._runner.receipts_path)
        else:
            # The executor's dispatcher writes receipts through a SEPARATE
            # ReceiptStore instance (its own in-memory index). Recompute this
            # read-side index from the append-only log so per-step evidence
            # reflects receipts the dispatcher appended AFTER this instance was
            # first constructed (Gate 5 multi-step: step N+1 receipts must be
            # visible to the loop's evidence evaluation).
            self._receipts_inst._recompute_from_log()
        return self._receipts_inst

    # ------------------------------------------------------------------ #
    # Closed loop                                                        #
    # ------------------------------------------------------------------ #
    async def run_closed_loop(
        self, directive: "CognitiveDirective | None" = None
    ) -> CognitiveLoopResult:
        """Run one bounded closed cognitive loop.

        Default shape (Gate 4 acceptance):
            1. observe         -> snapshot of canonical state
            2. understand      -> directive = reasoner.reason(observation)
            3. plan            -> canonical mission plan from the directive
            4. govern ONCE     -> single constitutional approval
            5. execute         -> APCB + Herdr + principal worker (via runner)
            6. observe outcome -> re-observe canonical state after each run
            7. evaluate        -> evidence from observer + store + receipts
            8. decide next     -> bounded continue/stop (no Founder relay)
            9. execute next    -> loop continues only under the bound

        A directive may be injected directly for deterministic unit tests; when
        omitted the injected reasoner produces it from the observation (R1).
        """
        # 1. OBSERVE — snapshot of canonical state (context for the loop).
        observation = self._observer.observe()

        # 2. UNDERSTAND — the injected reasoner turns the observation into a
        #    bounded directive. This is the acceptance item (2); the loop never
        #    hard-codes a directive when a reasoner is wired (R1).
        if directive is None:
            if self._reasoner is None:
                raise RuntimeError(
                    "CognitiveExecutive requires a reasoner or an explicit directive"
                )
            directive = self._reasoner.reason(observation)

        # 3. PLAN — canonical mission plan from the directive.
        plan = self._planner.plan_from_directive(directive)

        # 4. GOVERN ONCE — single constitutional approval at the start. A second
        #    call on the same plan propagates DuplicateGovernanceError; the loop
        #    never adds per-step approvals.
        self._planner.govern(plan)

        orchestrator = self._orchestrator()
        store = orchestrator.store
        mission_id = plan.mission_id
        bound = max(1, min(self.max_steps, directive.max_steps))

        decisions: list[dict[str, Any]] = []
        for step_count in range(1, bound + 1):
            completed_before = len(self._completed_step_ids(plan, store))
            await orchestrator.run(
                mission_id,
                principal="aether.mission-orchestrator",
                maximum_steps=1,
            )
            # 6. OBSERVE OUTCOME — re-observe canonical state after each run
            #    (R2). The outcome feeds evidence evaluation and the next-step
            #    decision, exactly as Gate 4 requires.
            self._observer.observe()
            status = store.current_status(mission_id)
            remaining = self._remaining_steps(plan, store)
            progress_made = (
                len(self._completed_step_ids(plan, store)) > completed_before
            )
            attempted = self._last_attempted_step(store, mission_id) or plan.steps[0].step_id
            # 7/8. EVIDENCE + DECIDE — the just-attempted step's observed outcome
            #       grounds the continue/stop decision (Gate 5 acceptance item 4).
            step_evidence = self._step_evidence(plan, store, mission_id, attempted)
            action, rationale = self.decide_next(
                status,
                remaining,
                step_count,
                bound,
                progress_made=progress_made,
                evidence=step_evidence,
            )
            decisions.append(
                {"step_id": attempted, "action": action, "rationale": rationale}
            )
            if action == "stop":
                break

        status = store.current_status(mission_id)
        steps_executed = self._completed_step_ids(plan, store)

        if status == MissionStatus.COMPLETED:
            await self._try_finalize(orchestrator, mission_id, steps_executed)

        evidence = self._evaluate_evidence(plan, store, mission_id, decisions)

        return CognitiveLoopResult(
            mission_id=mission_id,
            status=status.value,
            steps_executed=steps_executed,
            evidence_evaluations=tuple(evidence),
            decisions=tuple(decisions),
            governance_count=1,
            completed=status == MissionStatus.COMPLETED,
        )

    # ------------------------------------------------------------------ #
    # Decide next (bounded, deterministic, evidence-driven)               #
    # ------------------------------------------------------------------ #
    @staticmethod
    def decide_next(
        status: MissionStatus,
        remaining_steps: int,
        step_count: int,
        bound: int,
        progress_made: bool = True,
        evidence: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return (action, rationale): "continue" or "stop".

        Terminal mission state always stops. Non-progress states
        (PAUSED / WAITING_APPROVAL / REVIEW_REQUIRED) stop as "blocked" ONLY
        when no step progress was made (R4): the loop must not churn without
        advancing. A PAUSED continuation checkpoint after a completed step
        (progress_made=True) still continues under the bound.

        Evidence-driven (Gate 5 acceptance item 4): when `evidence` for the just
        attempted step is supplied and shows the step did NOT complete (failed /
        missing artifact / non-terminal receipt), the loop stops with the
        evidence-named rationale — the decision is grounded in the observed
        outcome, not just the status machine.
        """
        if evidence is not None:
            attempt = str(evidence.get("attempt_status") or "none")
            artifact = bool(evidence.get("artifact_present"))
            if attempt == "failed" or not artifact:
                return (
                    "stop",
                    f"step evidence failed (attempt={attempt}, artifact_present={artifact})",
                )
        if status in _TERMINAL_STATUSES:
            return "stop", f"mission terminal state={status.value}"
        if status in {
            MissionStatus.WAITING_APPROVAL,
            MissionStatus.REVIEW_REQUIRED,
            MissionStatus.DRAFT,
        }:
            return "stop", f"mission non-progress state={status.value} (blocked)"
        if status == MissionStatus.PAUSED and not progress_made:
            return "stop", "mission paused without step progress (blocked)"
        if remaining_steps <= 0:
            return "stop", "all plan steps completed"
        if step_count >= bound:
            return "stop", f"bounded at max_steps={bound}"
        return (
            "continue",
            f"mission {status.value} with {remaining_steps} step(s) remaining under bound {bound}",
        )

    # ------------------------------------------------------------------ #
    # Evidence + helpers                                                  #
    # ------------------------------------------------------------------ #
    def _step_evidence(
        self,
        plan,
        store,
        mission_id: str,
        step_id: str,
    ) -> dict[str, Any]:
        """Build the evidence dict for ONE just-attempted step (Gate 5 item 4).

        Mirrors the per-step fields of _evaluate_evidence so the loop's
        continue/stop decision is grounded in the observed outcome: attempt
        status, ADR-0057 artifact presence, and the APCB receipt terminal.
        Unknown step ids degrade to a neutral evidence (no stop trigger).
        """
        step = next((item for item in plan.steps if item.step_id == step_id), None)
        if step is None:
            return {"step_id": step_id, "attempt_status": "none", "artifact_present": False}
        latest = store.latest_attempt(mission_id, step.step_id)
        metadata = dict(step.action.metadata or {})
        work_id = str(metadata.get(MISSION_WORK_ID) or "WORK-PCP-003")
        return {
            "step_id": step.step_id,
            "attempt_status": latest.status.value if latest is not None else "none",
            "artifact_present": self._artifact_authoritative(metadata, mission_id),
            "terminal_outcome": self._receipt_terminal(mission_id, work_id),
        }

    def _evaluate_evidence(
        self,
        plan,
        store,
        mission_id: str,
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for step in plan.steps:
            latest = store.latest_attempt(mission_id, step.step_id)
            metadata = dict(step.action.metadata or {})
            work_id = str(metadata.get(MISSION_WORK_ID) or "WORK-PCP-003")
            decision = next(
                (d for d in decisions if d["step_id"] == step.step_id),
                {"action": "stop"},
            )
            evidence.append(
                {
                    "step_id": step.step_id,
                    "attempt_status": latest.status.value if latest is not None else "none",
                    "artifact_present": self._artifact_authoritative(metadata, mission_id),
                    "terminal_outcome": self._receipt_terminal(mission_id, work_id),
                    "decision": decision["action"],
                }
            )
        return evidence

    def _remaining_steps(self, plan, store) -> int:
        completed = self._completed_step_ids(plan, store)
        return len(plan.steps) - len(completed)

    @staticmethod
    def _completed_step_ids(plan, store) -> tuple[str, ...]:
        completed = tuple(
            step.step_id
            for step in plan.steps
            if (
                latest := store.latest_attempt(plan.mission_id, step.step_id)
            )
            is not None
            and latest.status == MissionStepStatus.COMPLETED
        )
        return completed

    @staticmethod
    def _last_attempted_step(store, mission_id: str) -> str | None:
        attempts = store.attempts(mission_id)
        if not attempts:
            return None
        return attempts[-1].step_id

    def _artifact_authoritative(
        self, metadata: dict[str, Any], mission_id: str
    ) -> bool:
        """ADR-0057 artifact authority: the deliverable must exist AND carry a
        matching canonical envelope (protocol/mission_id/work_id/principal/attempt),
        not merely be a file with the right name (R3).

        Reuses the mission-level verifier (build_mission_artifact_verify) with a
        WorkItemView built from the step's canonical metadata.
        """
        expected = metadata.get(MISSION_EXPECTED_ARTIFACT)
        workspace = metadata.get(MISSION_WORKSPACE_ID) or ""
        if not expected or not workspace or "://" in workspace:
            return False
        verifier = build_mission_artifact_verify(str(expected))
        if verifier is None:
            return False
        work = WorkItemView(
            work_id=str(metadata.get(MISSION_WORK_ID) or "WORK-PCP-003"),
            mission_id=mission_id,
            principal_id=str(metadata.get(MISSION_PRINCIPAL_ID) or ""),
            required_capabilities=(),
            workspace_id=workspace,
            authorized=True,
            execution_ready=True,
            attempt_number=1,
            execution_profile=str(metadata.get(MISSION_EXECUTION_PROFILE) or ""),
            metadata=metadata,
        )
        return verifier(work)

    def _receipt_terminal(self, mission_id: str, work_id: str) -> str | None:
        latest = self._receipts().latest_for_work(work_id, mission_id=mission_id)
        return latest.terminal_outcome if latest is not None else None

    @staticmethod
    async def _try_finalize(
        orchestrator: MissionOrchestrator,
        mission_id: str,
        completed_step_ids: tuple[str, ...],
    ) -> None:
        """Best-effort outcome evidence. Never crashes the loop.

        finalize validates the caller as a trusted principal; the orchestrator
        identity is not in the trusted set, so a MissionBlocked here is expected
        and swallowed (the loop completion is already authoritative in the store).
        """
        try:
            await orchestrator.finalize(
                mission_id,
                achieved=True,
                summary=f"Gate 4 closed loop completed {len(completed_step_ids)} step(s).",
                lessons=(
                    "Observe -> plan -> govern-once -> execute -> evaluate -> "
                    "decide-next closed loop exercised without Founder relay.",
                ),
                principal="aether.mission-orchestrator",
            )
        except MissionBlocked:
            LOG.warning("cognitive_executive: finalize skipped for %s (best-effort evidence)", mission_id)
