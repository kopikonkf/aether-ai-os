"""MISSION-PCP-003 WORK-1 — CognitiveObserver deterministic state observe.

Tests for aether.executive.cognitive_observer:
  - empty stores (None) produce an empty deterministic snapshot;
  - a fake mission store populates mission_states correctly;
  - a real ReceiptStore in tmp_path populates receipt_states + reconcile_notes;
  - workspace artifacts are sorted file names (subdirs excluded);
  - a raising store degrades to empty + "observe_degraded" (never raises);
  - two observers over the same state produce identical summaries.

Deterministic: fake stores and tmp_path only — no network, no live herdr.
"""
from __future__ import annotations

from pathlib import Path

from aether.apcb.contracts import (
    BridgeExecutionReceipt,
    ExecutionReceiptStatus,
)
from aether.apcb.receipt_store import ReceiptStore
from aether.contracts.missions import MissionOutcomeState, MissionStatus, MissionStepStatus
from aether.executive.cognitive_observer import CognitiveObserver


class _Plan:
    def __init__(self, mission_id: str, n_steps: int):
        self.mission_id = mission_id
        self.steps = [object() for _ in range(n_steps)]


class _Attempt:
    def __init__(self, step_id: str, status: MissionStepStatus):
        self.step_id = step_id
        self.status = status


class _Outcome:
    def __init__(self, state: MissionOutcomeState):
        self.state = state


class _RaisingStore:
    def list_plans(self):
        return [_Plan("M-1", 1)]

    def current_status(self, mission_id: str):
        raise RuntimeError("store is down")

    def attempts(self, mission_id: str):
        return []

    def value_evidence(self, mission_id: str):
        return []

    def latest_outcome(self, mission_id: str):
        return None


class FakeMissionStore:
    def __init__(self, plans, statuses, attempts, outcomes):
        self._plans = plans
        self._statuses = statuses
        self._attempts = attempts
        self._outcomes = outcomes

    def list_plans(self):
        return self._plans

    def current_status(self, mission_id: str) -> MissionStatus | None:
        return self._statuses.get(mission_id)

    def attempts(self, mission_id: str):
        return self._attempts.get(mission_id, [])

    def value_evidence(self, mission_id: str):
        return []

    def latest_outcome(self, mission_id: str):
        return self._outcomes.get(mission_id)


def test_observe_empty_store():
    observation = CognitiveObserver(None, None, None).observe()
    assert observation.mission_states == ()
    assert observation.receipt_states == ()
    assert observation.reconcile_notes == ()
    assert observation.workspace_artifacts == ()
    assert "0 mission" in observation.summary
    assert observation.observed_at


def test_observe_mission_states():
    store = FakeMissionStore(
        plans=[_Plan("M-1", 3)],
        statuses={"M-1": MissionStatus.RUNNING},
        attempts={
            "M-1": [
                _Attempt("step-a", MissionStepStatus.COMPLETED),
                _Attempt("step-b", MissionStepStatus.RUNNING),
            ]
        },
        outcomes={"M-1": _Outcome(MissionOutcomeState.VERIFIED)},
    )
    observation = CognitiveObserver(store, None, None).observe()
    assert len(observation.mission_states) == 1
    state = observation.mission_states[0]
    assert state["mission_id"] == "M-1"
    assert state["status"] == "running"
    assert state["step_count"] == 3
    assert state["completed_steps"] == 1
    assert state["attempt_count"] == 2
    assert state["latest_attempt_status"] == "running"
    assert state["latest_outcome_state"] == "verified"


def test_observe_receipt_states(tmp_path: Path):
    store = ReceiptStore(tmp_path / "receipts.jsonl")
    store.persist(
        BridgeExecutionReceipt(
            work_id="WORK-1",
            attempt_number=1,
            principal_id="qwen",
            mission_id="MISSION-1",
            state=ExecutionReceiptStatus.TERMINAL,
            terminal_outcome="completed",
        )
    )
    store.persist(
        BridgeExecutionReceipt(
            work_id="WORK-2",
            attempt_number=1,
            principal_id="claude",
            mission_id="MISSION-2",
            state=ExecutionReceiptStatus.CLAIMED,
        )
    )
    store.append_note(
        {
            "note_type": "reconcile_artifact_found",
            "work_id": "WORK-2",
            "mission_id": "MISSION-2",
            "principal_id": "claude",
            "attempt_number": 1,
            "new_terminal_outcome": "completed",
        }
    )
    observation = CognitiveObserver(None, store, None).observe()
    assert len(observation.receipt_states) == 2
    assert len(observation.reconcile_notes) == 1

    terminal = observation.receipt_states[0]
    assert terminal["mission_id"] == "MISSION-1"
    assert terminal["work_id"] == "WORK-1"
    assert terminal["attempt_number"] == 1
    assert terminal["principal_id"] == "qwen"
    assert terminal["state"] == "terminal"
    assert terminal["terminal_outcome"] == "completed"
    assert terminal["error"] is None

    claimed = observation.receipt_states[1]
    assert claimed["state"] == "claimed"
    assert claimed["terminal_outcome"] is None

    note = observation.reconcile_notes[0]
    assert note["recorded_at"]
    assert note["note_type"] == "reconcile_artifact_found"
    assert note["work_id"] == "WORK-2"
    assert note["mission_id"] == "MISSION-2"
    assert note["principal_id"] == "claude"
    assert note["attempt_number"] == 1
    assert note["new_terminal_outcome"] == "completed"


def test_observe_workspace_artifacts(tmp_path: Path):
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("n", encoding="utf-8")
    observation = CognitiveObserver(None, None, str(tmp_path)).observe()
    assert observation.workspace_artifacts == ("a.md", "b.txt")


def test_observe_fail_soft():
    observation = CognitiveObserver(_RaisingStore(), None, None).observe()
    assert observation.mission_states == ()
    assert "observe_degraded" in observation.summary


def test_summary_deterministic(tmp_path: Path):
    store = FakeMissionStore(
        plans=[_Plan("M-1", 2)],
        statuses={"M-1": MissionStatus.COMPLETED},
        attempts={"M-1": [_Attempt("step-a", MissionStepStatus.COMPLETED)]},
        outcomes={"M-1": _Outcome(MissionOutcomeState.REALIZED)},
    )
    receipts = ReceiptStore(tmp_path / "r.jsonl")
    receipts.persist(
        BridgeExecutionReceipt(
            work_id="WORK-1",
            attempt_number=1,
            principal_id="qwen",
            mission_id="M-1",
            state=ExecutionReceiptStatus.TERMINAL,
            terminal_outcome="completed",
        )
    )
    (tmp_path / "work.md").write_text("x", encoding="utf-8")

    a = CognitiveObserver(store, receipts, str(tmp_path)).observe()
    b = CognitiveObserver(store, receipts, str(tmp_path)).observe()
    assert a.summary == b.summary
    assert a.mission_states == b.mission_states
    assert a.receipt_states == b.receipt_states
