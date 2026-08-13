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
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.missions import (
    MissionBlocked,
    MissionStatus,
    MissionStepStatus,
)
from aether.events import EventBus
from aether.missions.canonical_mapper import MISSION_EXPECTED_ARTIFACT, MISSION_WORK_ID, MISSION_WORKSPACE_ID
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
        return self._receipts_inst

    # ------------------------------------------------------------------ #
    # Closed loop                                                        #
    # ------------------------------------------------------------------ #
    async def run_closed_loop(
        self, directive: "CognitiveDirective"
    ) -> CognitiveLoopResult:
        # 1. OBSERVE — snapshot of canonical state (context for the loop).
        self._observer.observe()

        # 2. PLAN — canonical mission plan from the directive.
        plan = self._planner.plan_from_directive(directive)

        # 3. GOVERN ONCE — single constitutional approval at the start. A second
        #    call on the same plan propagates DuplicateGovernanceError; the loop
        #    never adds per-step approvals.
        self._planner.govern(plan)

        orchestrator = self._orchestrator()
        store = orchestrator.store
        mission_id = plan.mission_id
        bound = max(1, min(self.max_steps, directive.max_steps))

        decisions: list[dict[str, Any]] = []
        for step_count in range(1, bound + 1):
            await orchestrator.run(
                mission_id,
                principal="aether.mission-orchestrator",
                maximum_steps=1,
            )
            status = store.current_status(mission_id)
            remaining = self._remaining_steps(plan, store)
            action, rationale = self.decide_next(status, remaining, step_count, bound)
            attempted = self._last_attempted_step(store, mission_id) or plan.steps[0].step_id
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
    # Decide next (bounded, deterministic)                                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def decide_next(
        status: MissionStatus,
        remaining_steps: int,
        step_count: int,
        bound: int,
    ) -> tuple[str, str]:
        """Return (action, rationale): "continue" or "stop".

        Terminal mission state always stops. Otherwise the loop continues only
        while steps remain AND the iteration count is under the bound.
        """
        if status in _TERMINAL_STATUSES:
            return "stop", f"mission terminal state={status.value}"
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
                    "artifact_present": self._artifact_present(metadata),
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

    @staticmethod
    def _artifact_present(metadata: dict[str, Any]) -> bool:
        expected = metadata.get(MISSION_EXPECTED_ARTIFACT)
        workspace = metadata.get(MISSION_WORKSPACE_ID) or ""
        if not expected or not workspace or "://" in workspace:
            return False
        try:
            return (Path(workspace) / str(expected)).is_file()
        except OSError:
            return False

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
