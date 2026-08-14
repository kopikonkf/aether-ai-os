"""MISSION-PCP-003 WORK-4 — CognitiveExecutive closed-loop driver tests.

Tests aether.executive.cognitive_executive running the FULL closed loop:
    observe -> plan -> govern-once -> execute -> observe-outcome -> evaluate ->
    decide next -> (bounded) -> next
without a Founder relay between steps. A deterministic MockHerdrAdapter stands
in for the live pane and writes the deliverable artifact on prompt so the
ADR-0057 artifact authority passes. No live herdr, no network.

Assertions cover: single-step completion, governance exactly once, the
max_steps bound, evidence recording, no post-govern founder decisions, failure
stopping the loop, observe-before-plan, and the duplicate-governance invariant.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aether.apcb import AdapterConformanceStatus
from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.contracts.missions import (
    MissionBudget,
    MissionDecisionType,
    MissionLane,
    MissionRisk,
    MissionStep,
    MissionStatus,
    OpportunityEvidence,
    OpportunityEvidenceStance,
)
from aether.executive.cognitive_executive import CognitiveExecutive, CognitiveLoopResult
from aether.executive.cognitive_observer import CognitiveObservation, CognitiveObserver
from aether.executive.cognitive_planner import CognitivePlanner, DuplicateGovernanceError
from aether.executive.cognitive_reasoner import CognitiveDirective, RuleBasedReasoner
from aether.missions.live_runner import MissionCognitiveRunner
from aether.missions.orchestrator import MissionOrchestrator


class _Obs:
    def __init__(self, status, is_terminal=False, error=None):
        self.agent_ref = ""
        self.status = status
        self.is_terminal = is_terminal
        self.error = error


class MockHerdrAdapter:
    """Deterministic fake of the live HerdrExecutionAdapter surface.

    When write_artifact=True, prompt_agent parses the canonical envelope out of
    the prompt and writes the expected deliverable into the workspace with a
    MATCHING envelope (mission_id/work_id/principal/attempt), so the ADR-0057
    artifact authority accepts the step.
    """

    def __init__(self, wait_status="done", write_artifact=True, expected_artifact="WORK-PCP-003.md"):
        self.wait_status = wait_status
        self.write_artifact = write_artifact
        self.expected_artifact = expected_artifact
        self.calls: list[str] = []
        self.agent_ref = "herdr://pane/w7:p3"

    def detect_adapter(self, herdr_agent_kind: str) -> AdapterConformanceStatus:
        self.calls.append("detect_adapter")
        return AdapterConformanceStatus.HEALTHY

    def ensure_agent(self, workspace_ref, principal_id, herdr_agent_kind=None):
        self.calls.append("ensure_agent")
        return self.agent_ref

    def prompt_agent(self, agent_ref, task_context):
        self.calls.append("prompt_agent")
        if self.write_artifact:
            self._write_artifact_from_prompt(task_context)
        return f"{agent_ref}/prompt"

    def _write_artifact_from_prompt(self, prompt_text: str) -> None:
        header = _parse_prompt(prompt_text)
        workspace_id = header.get("workspace_id") or ""
        if not workspace_id:
            return
        ws = Path(workspace_id)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / self.expected_artifact).write_text(
            envelope_text(
                work_id=header.get("work_id") or "WORK-PCP-003",
                principal_id=header.get("principal_id") or "chatgpt",
                attempt=int(header.get("attempt") or 1),
                mission_id=header.get("mission_id") or "",
            ),
            encoding="utf-8",
        )

    def wait_agent(self, agent_ref, timeout_seconds):
        self.calls.append("wait_agent")
        return _Obs(
            self.wait_status,
            is_terminal=self.wait_status in ("done", "blocked", "terminated"),
        )

    def read_agent(self, agent_ref, limit_bytes=8192):
        self.calls.append("read_agent")
        return "[pcp-003 mock] deliverable produced."

    def observe_agent(self, agent_ref):
        self.calls.append("observe_agent")
        return _Obs(self.wait_status, is_terminal=self.wait_status == "done")

    def recover_agent(self, agent_ref):
        self.calls.append("recover_agent")
        return self.observe_agent(agent_ref)


def _parse_prompt(text: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in text.splitlines()[:60]:
        line = line.strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        header[key.strip().lower()] = value.strip()
    return header


def envelope_text(work_id="WORK-PCP-003", principal_id="chatgpt", attempt=1, mission_id="MISSION-PCP-003") -> str:
    return (
        "protocol: aether.apcb.task.v1\n"
        f"work_id: {work_id}\n"
        f"mission_id: {mission_id}\n"
        f"principal_id: {principal_id}\n"
        f"attempt: {attempt}\n"
        "\n"
        "## Body\n"
        "produced the canonical deliverable artifact."
    )


def make_runner(tmp_path: Path) -> MissionCognitiveRunner:
    return MissionCognitiveRunner(
        store_path=tmp_path / "missions.sqlite3",
        receipts_path=tmp_path / "receipts.jsonl",
        registry_path=None,
        workspace_override=str(tmp_path / "mission-ws"),
        events_path=tmp_path / "events.jsonl",
    )


def make_planner(runner: MissionCognitiveRunner) -> CognitivePlanner:
    orchestrator = MissionOrchestrator(
        runner.store, _DummyExecutor(), maximum_steps_per_run=5
    )
    return CognitivePlanner(orchestrator)


class _DummyExecutor:
    async def execute(self, proposal):
        raise AssertionError("planner path must never execute a step")

    async def approval_result(self, approval_id):
        return None


def make_directive(ws: str, *, max_steps: int = 1, budget_usd: float = 10.0) -> CognitiveDirective:
    return CognitiveDirective(
        objective="Address observed Aether state",
        expected_artifact="WORK-PCP-003.md",
        principal_id="chatgpt",
        execution_profile="herdr:opencode",
        workspace_id=ws,
        capabilities=("systems_integration",),
        max_steps=max_steps,
        budget_usd=budget_usd,
        stop_conditions=("stop when budget exhausted",),
        rationale="rule-based: deterministic default",
    )


def make_executive(
    runner: MissionCognitiveRunner,
    adapter,
    *,
    max_steps: int = 3,
    observe_calls: list[int] | None = None,
) -> CognitiveExecutive:
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    observer = CountingObserver(
        CognitiveObserver(runner.store, ReceiptStore(runner.receipts_path), str(ws)),
        observe_calls,
    )
    planner = make_planner(runner)
    reasoner = RuleBasedReasoner(workspace_override=str(ws))
    return CognitiveExecutive(
        runner, observer, reasoner, planner, max_steps=max_steps, adapter=adapter
    )


class CountingObserver:
    """Record observe() invocations to prove observe-before-plan."""

    def __init__(self, inner: CognitiveObserver, sink: list[int] | None = None):
        self._inner = inner
        self._sink = sink

    def observe(self) -> CognitiveObservation:
        if self._sink is not None:
            self._sink.append(1)
        return self._inner.observe()


# ---------------------------------------------------------------------------
# 1. Single-step closed loop completes
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_closed_loop_completes_single_step(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    executive = make_executive(runner, adapter)

    result: CognitiveLoopResult = await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    assert result.completed is True
    assert result.status == MissionStatus.COMPLETED.value
    assert result.governance_count == 1
    assert result.steps_executed == ("step-1",)
    assert runner.store.current_status(result.mission_id) == MissionStatus.COMPLETED


# ---------------------------------------------------------------------------
# 2. Governance happens exactly once
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_governance_exactly_once(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    executive = make_executive(runner, adapter)

    result = await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    assert result.governance_count == 1
    decision = runner.store.get_decision(result.mission_id)
    assert decision is not None
    assert decision.decision == MissionDecisionType.APPROVE


# ---------------------------------------------------------------------------
# 3. Loop is bounded at max_steps (never infinite)
# ---------------------------------------------------------------------------
def _plan_steps(directive: CognitiveDirective) -> tuple[MissionStep, MissionStep]:
    def step(step_id: str, work_id: str) -> MissionStep:
        metadata = {
            "mission_principal_id": directive.principal_id,
            "mission_execution_profile": directive.execution_profile,
            "mission_workspace_id": directive.workspace_id,
            "mission_capabilities": list(directive.capabilities),
            "mission_expected_artifact": directive.expected_artifact,
            "mission_work_id": work_id,
            "objective": directive.objective,
            "constraints": list(directive.stop_conditions),
            "acceptance_criteria": [f"produce {directive.expected_artifact}"],
        }
        return MissionStep(
            step_id=step_id,
            title=f"Step {step_id}",
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

    return step("step-1", "WORK-PCP-003"), step("step-2", "WORK-PCP-003-S2")


@pytest.mark.asyncio
async def test_loop_bounded_max_steps(tmp_path: Path):
    # A 2-step plan with a max_steps=1 bound: the loop must stop after ONE
    # iteration (mission PAUSED at the continuation checkpoint) and never run
    # step-2 or spin forever.
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    ws = str(Path(runner.workspace_override))
    directive = make_directive(ws, max_steps=1)

    # Build a 2-step plan directly over the runner store.
    orch = MissionOrchestrator(runner.store, _DummyExecutor(), maximum_steps_per_run=1)
    brief = orch.intake_opportunity(
        title="Bounded cognitive executive step",
        lane=MissionLane.EXTERNAL_VALUE,
        problem_statement="Bounded step for the executive loop.",
        beneficiary="Aether cognitive executive",
        value_proposition="Produce a deterministic deliverable.",
        probability_success=0.5,
        upside_usd=10.0,
        estimated_cost_usd=1.0,
        estimated_duration_hours=0.5,
        revenue_hypothesis="Accepted deliverable advances the closed-loop proof.",
        assumptions=("Small, reversible, evidence-first.",),
        evidence=(
            OpportunityEvidence(
                source="evidence-a", independent_source_id="evidence-a",
                statement="Deterministic supporting evidence.",
                stance=OpportunityEvidenceStance.SUPPORTS,
                external_reference="https://evidence.invalid/a",
            ),
            OpportunityEvidence(
                source="evidence-b", independent_source_id="evidence-b",
                statement="Second independent supporting evidence.",
                stance=OpportunityEvidenceStance.SUPPORTS,
                external_reference="https://evidence.invalid/b",
            ),
        ),
        risk=MissionRisk.LOW,
        confidence=0.6,
    )
    step1, step2 = _plan_steps(directive)
    plan = orch.create_plan(
        brief_id=brief.brief_id,
        objective=directive.objective,
        northstar_alignment="Creates external value while preserving truth, reversibility, and evidence-first execution.",
        northstar_principle_ids=("SP1", "SP5"),
        strategy_tags=("business_experimentation",),
        steps=(step1, step2),
        budget=MissionBudget(max_cost_usd=10.0, max_duration_seconds=600, max_step_attempts=1),
        stop_conditions=directive.stop_conditions,
    )

    class StubPlanner:
        def __init__(self, orchestrator, plan):
            self._orchestrator = orchestrator
            self._plan = plan
            self._governed: set[str] = set()

        def plan_from_directive(self, directive):
            return self._plan

        def govern(self, plan):
            if plan.mission_id in self._governed:
                raise DuplicateGovernanceError(plan.mission_id)
            self._governed.add(plan.mission_id)
            return self._orchestrator.decide(
                plan.mission_id, approved=True, principal="founder",
                channel="constitutional", reason="test govern",
            )

    Path(ws).mkdir(parents=True, exist_ok=True)
    observer = CountingObserver(
        CognitiveObserver(runner.store, ReceiptStore(runner.receipts_path), ws), None
    )
    executive = CognitiveExecutive(
        runner, observer, RuleBasedReasoner(workspace_override=ws),
        StubPlanner(orch, plan), max_steps=1, adapter=adapter,
    )

    result = await executive.run_closed_loop(directive)
    assert result.completed is False
    assert result.status == MissionStatus.PAUSED.value
    assert len(result.decisions) == 1
    assert result.decisions[0]["action"] == "stop"
    assert "bounded" in result.decisions[0]["rationale"]
    assert adapter.calls.count("prompt_agent") == 1  # step-2 never dispatched


# ---------------------------------------------------------------------------
# 4. Evidence evaluations recorded
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_evidence_evaluations_recorded(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    executive = make_executive(runner, adapter)

    result = await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    assert len(result.evidence_evaluations) == 1
    evidence = result.evidence_evaluations[0]
    assert evidence["step_id"] == "step-1"
    assert evidence["attempt_status"] == "completed"
    assert evidence["artifact_present"] is True
    assert evidence["terminal_outcome"] == "completed"


# ---------------------------------------------------------------------------
# 5. No founder relay after start
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_founder_relay_after_start(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    executive = make_executive(runner, adapter)

    result = await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    # Exactly one APPROVE decision; no additional approve transitions from the
    # loop itself (govern once, execute without per-step approvals).
    decision = runner.store.get_decision(result.mission_id)
    assert decision is not None
    assert decision.decision == MissionDecisionType.APPROVE
    approved_transitions = [
        t for t in runner.store.transitions(result.mission_id)
        if t.to_status == MissionStatus.APPROVED
    ]
    assert len(approved_transitions) == 1


# ---------------------------------------------------------------------------
# 6. Failed step stops the loop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_step_stops_loop(tmp_path: Path):
    runner = make_runner(tmp_path)
    # write_artifact=False -> worker "says done" but no deliverable -> the
    # artifact authority downgrades it and the mission step FAILS.
    adapter = MockHerdrAdapter(wait_status="done", write_artifact=False)
    executive = make_executive(runner, adapter)

    result = await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    assert result.completed is False
    assert result.status in (MissionStatus.FAILED.value, MissionStatus.STOPPED.value)
    assert result.governance_count == 1
    assert result.decisions[-1]["action"] == "stop"


# ---------------------------------------------------------------------------
# 7. Observe used before plan
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_observe_used_before_plan(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    observe_calls: list[int] = []
    executive = make_executive(runner, adapter, observe_calls=observe_calls)

    await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    assert len(observe_calls) >= 1


# ---------------------------------------------------------------------------
# 8. Duplicate governance raises
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicate_governance_raises(tmp_path: Path):
    runner = make_runner(tmp_path)
    planner = make_planner(runner)
    directive = make_directive(str(Path(runner.workspace_override)))
    plan = planner.plan_from_directive(directive)
    planner.govern(plan)
    with pytest.raises(DuplicateGovernanceError):
        planner.govern(plan)


# ---------------------------------------------------------------------------
# 9. R1: reasoner is called when no directive is injected (understand wired)
# ---------------------------------------------------------------------------
class RecordingReasoner:
    def __init__(self, inner: RuleBasedReasoner):
        self._inner = inner
        self.calls: list[CognitiveObservation] = []

    def reason(self, observation: CognitiveObservation) -> CognitiveDirective:
        self.calls.append(observation)
        return self._inner.reason(observation)


@pytest.mark.asyncio
async def test_closed_loop_uses_reasoner_when_no_directive(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    observer = CognitiveObserver(runner.store, ReceiptStore(runner.receipts_path), str(ws))
    planner = make_planner(runner)
    reasoner = RecordingReasoner(RuleBasedReasoner(workspace_override=str(ws)))
    executive = CognitiveExecutive(
        runner, observer, reasoner, planner, max_steps=1, adapter=adapter
    )

    # No directive injected: the loop MUST derive it from observation (R1).
    result = await executive.run_closed_loop()
    assert result.completed is True
    assert result.governance_count == 1
    assert len(reasoner.calls) == 1
    assert reasoner.calls[0].observed_at  # reasoner saw a real observation


# ---------------------------------------------------------------------------
# 10. R2: observe outcome is called again AFTER execution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_closed_loop_observes_outcome_after_execution(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    observe_calls: list[int] = []
    executive = make_executive(runner, adapter, observe_calls=observe_calls)

    await executive.run_closed_loop(
        make_directive(str(Path(runner.workspace_override)))
    )
    # observe before plan (1) + observe outcome after the run (>=1) = >=2
    assert len(observe_calls) >= 2


# ---------------------------------------------------------------------------
# 11. R3: evidence artifact check uses envelope authority (stale envelope fails)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_evidence_rejects_stale_artifact_envelope(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done", write_artifact=False)
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    # A file EXISTS but carries the WRONG mission envelope -> artifact_authority
    # must report artifact_present=False (R3), unlike a bare is_file() check.
    (ws / "WORK-PCP-003.md").write_text(
        envelope_text(mission_id="SOME-OTHER-MISSION"), encoding="utf-8"
    )
    executive = make_executive(runner, adapter)

    result = await executive.run_closed_loop(
        make_directive(str(ws))
    )
    ev = result.evidence_evaluations[0]
    assert ev["artifact_present"] is False
