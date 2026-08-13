"""MISSION-PCP-002 WORK-5 — live cognitive single-principal runner (deterministic).

Tests MissionCognitiveRunner assembling the full chain:
    MissionOrchestrator -> ApcbMissionActionExecutor -> APCBDispatcher
        -> canonical work_mapper -> mission-state observer -> artifact_verify

Acceptance path proven at the deterministic level: Aether produces a canonical
mission step, APCB "dispatches" to a mock principal worker, the worker writes
the deliverable artifact, and artifact authority produces completed evidence in
the mission store. NO live herdr, NO real dispatch — the mock adapter stands in
for the live pane (live smoke is owned by COORD).

Artifact envelope matches the canonical prompt (work_id/principal_id/attempt),
reusing the same authority the live worker would write.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aether.apcb import AdapterConformanceStatus, APCBDispatcher
from aether.contracts import MissionStatus
from aether.missions import MissionOrchestrator
from aether.missions.live_runner import MissionCognitiveRunner


class _Obs:
    def __init__(self, status, is_terminal=False, error=None):
        self.agent_ref = ""
        self.status = status
        self.is_terminal = is_terminal
        self.error = error


class MockHerdrAdapter:
    """Deterministic fake of the live HerdrExecutionAdapter surface."""

    def __init__(self, wait_status="done"):
        self.wait_status = wait_status
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
        return f"{agent_ref}/prompt"

    def wait_agent(self, agent_ref, timeout_seconds):
        self.calls.append("wait_agent")
        return _Obs(
            self.wait_status,
            is_terminal=self.wait_status in ("done", "blocked", "terminated"),
        )

    def read_agent(self, agent_ref, limit_bytes=8192):
        self.calls.append("read_agent")
        return "[pcp-002 mock] deliverable produced."

    def observe_agent(self, agent_ref):
        self.calls.append("observe_agent")
        return _Obs(self.wait_status, is_terminal=self.wait_status == "done")

    def recover_agent(self, agent_ref):
        self.calls.append("recover_agent")
        return self.observe_agent(agent_ref)


def envelope_text(work_id="WORK-PCP-002", principal_id="chatgpt", attempt=1) -> str:
    return (
        "protocol: aether.apcb.task.v1\n"
        f"work_id: {work_id}\n"
        "mission_id: MISSION-PCP-002\n"
        f"principal_id: {principal_id}\n"
        f"attempt: {attempt}\n"
        "\n"
        "## Body\n"
        "produced the canonical deliverable artifact."
    )


def make_runner(tmp_path: Path, *, pane_map_path=None) -> MissionCognitiveRunner:
    return MissionCognitiveRunner(
        store_path=tmp_path / "missions.sqlite3",
        receipts_path=tmp_path / "receipts.jsonl",
        registry_path=None,
        pane_map_path=pane_map_path,
        workspace_override=str(tmp_path / "mission-ws"),
        events_path=tmp_path / "events.jsonl",
    )


# ---------------------------------------------------------------------------
# (a) build_dispatcher assembles the full chain
# ---------------------------------------------------------------------------
def test_runner_builds_dispatcher_chain(tmp_path: Path):
    runner = make_runner(tmp_path)
    dispatcher = runner.build_dispatcher(MockHerdrAdapter())
    assert isinstance(dispatcher, APCBDispatcher)
    assert dispatcher.aether_state_observer is not None
    assert dispatcher.workspace_verify is not None
    assert dispatcher.artifact_verify is not None


# ---------------------------------------------------------------------------
# (b) acceptance path: completed mission with matching artifact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_cognitive_mission_completed(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "WORK-PCP-002.md").write_text(envelope_text(), encoding="utf-8")

    result = await runner.run_cognitive_mission(adapter, workspace=str(ws))
    assert result.status == MissionStatus.COMPLETED
    assert result.completed_step_ids == ("step-1",)

    attempts = runner.store.attempts(result.mission_id, step_id="step-1")
    assert len(attempts) == 1
    assert attempts[0].status.value == "completed"
    assert runner.store.current_status(result.mission_id) == MissionStatus.COMPLETED
    assert (ws / "WORK-PCP-002.md").is_file()
    assert "ensure_agent" in adapter.calls


# ---------------------------------------------------------------------------
# (c) artifact authority: done WITHOUT matching artifact -> not completed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_cognitive_mission_artifact_missing(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    # worker "says done" but no deliverable artifact in the workspace.

    result = await runner.run_cognitive_mission(adapter, workspace=str(ws))
    # The orchestrator rejects a completed step whose APCB terminal was
    # completed_without_artifact (ok=False from the executor) -> FAILED.
    assert result.status != MissionStatus.COMPLETED
    attempts = runner.store.attempts(result.mission_id, step_id="step-1")
    assert attempts[-1].status.value in ("failed",)
    assert not (ws / "WORK-PCP-002.md").exists()


# ---------------------------------------------------------------------------
# (d) F-07: mission already terminal -> no re-dispatch (observer wired)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_runner_mission_state_observer_stops(tmp_path: Path):
    runner = make_runner(tmp_path)
    adapter = MockHerdrAdapter(wait_status="done")
    ws = Path(runner.workspace_override)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "WORK-PCP-002.md").write_text(envelope_text(), encoding="utf-8")

    first = await runner.run_cognitive_mission(adapter, workspace=str(ws))
    assert first.status == MissionStatus.COMPLETED
    assert adapter.calls.count("ensure_agent") == 1

    # Re-run the SAME mission id through a fresh orchestrator over the same
    # store: the mission is already COMPLETED (terminal) so the run returns
    # terminal without dispatching again (mission-state authority, F-07).
    executor = runner.build_executor(MockHerdrAdapter(wait_status="done"))
    orchestrator = MissionOrchestrator(
        runner.store,
        executor,
        maximum_steps_per_run=5,
    )
    second = await orchestrator.run(first.mission_id, principal="founder")
    assert second.status == MissionStatus.COMPLETED
    assert adapter.calls.count("ensure_agent") == 1
