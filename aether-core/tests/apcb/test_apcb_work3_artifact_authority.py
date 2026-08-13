"""WORK-PCP-003 — artifact authority + pane-send no-fabrication (deterministic).

Covers WORK-1 recommendations 1, 2, 5 / ADR-0057 (K1) implemented in WORK-3:

  (a) aether_state_observer + artifact_verify wired into the dispatch path:
      a "completed" terminal requires the artifact (completed_with_artifact vs
      done_without_artifact); a failed/unknown observation whose artifact
      exists is promoted to completed with reconcile_artifact_found.
  (b) pane-send wait_agent returns unknown + non-terminal (never "done"), and
      _outcome_from_observation never turns unknown into completed.
  (c) reconcile emits reconcile_artifact_found in DispatchDecision.metadata
      when a terminal unknown/failed receipt has the artifact (append-only;
      the receipt is NOT rewritten, K2 still holds).

All tests are deterministic with a mock adapter — no live herdr, no repo
mutation, no dispatch to a real pane.
"""
from __future__ import annotations

from pathlib import Path

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


class MockAdapter:
    """Deterministic fake adapter. `wait_status` drives wait/observe."""

    def __init__(self, wait_status="done"):
        self.wait_status = wait_status
        self.calls: list[str] = []
        self.agent_ref = "herdr://pane/w7:p3"

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
            error="pane-send agent: no lifecycle" if self.wait_status == "unknown" else None,
        )

    def read_agent(self, agent_ref, limit_bytes=8192):
        self.calls.append("read_agent")
        return "[work-3 mock] output"

    def observe_agent(self, agent_ref):
        self.calls.append("observe_agent")
        return _Obs(
            self.wait_status,
            is_terminal=self.wait_status in ("done", "blocked", "terminated"),
        )

    def recover_agent(self, agent_ref):
        self.calls.append("recover_agent")
        return self.observe_agent(agent_ref)


class _Obs:
    def __init__(self, status, is_terminal=False, error=None):
        self.agent_ref = ""
        self.status = status
        self.is_terminal = is_terminal
        self.error = error


@pytest.fixture
def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


@pytest.fixture
def receipts(tmp_path) -> ReceiptStore:
    return ReceiptStore(tmp_path / "receipts.jsonl")


def make_dispatcher(
    profiles,
    receipts,
    adapter,
    mission_state=None,
    artifact_verify=None,
    workspace_verify=None,
):
    gate = ConformanceGate(
        profiles, probe=lambda kind: AdapterConformanceStatus.HEALTHY
    )
    return APCBDispatcher(
        profiles=profiles,
        receipts=receipts,
        conformance_gate=gate,
        adapter=adapter,
        aether_state_observer=(lambda mid: mission_state) if mission_state else None,
        workspace_verify=workspace_verify,
        artifact_verify=artifact_verify,
        wait_timeout_seconds=0.5,
    )


def ready_work(**overrides) -> WorkItemView:
    view = WorkItemView(
        work_id="WORK-PCP-003",
        mission_id="MISSION-PCP-001",
        principal_id="qwen",
        required_capabilities=("coding",),
        workspace_id="workspace://default",
        authorized=True,
        execution_ready=True,
        awaiting_approval=False,
        attempt_number=1,
        execution_profile="herdr:cline",
        metadata={"objective": "implement artifact authority"},
    )
    return WorkItemView(**{**view.__dict__, **overrides})


# ---------------------------------------------------------------------------
# (a) terminal "completed" requires the artifact (ADR-0057 §4)
# ---------------------------------------------------------------------------
class TestDispatchArtifactAuthority:
    def test_completed_with_artifact(self, profiles, receipts, tmp_path):
        adapter = MockAdapter(wait_status="done")
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("ok", encoding="utf-8")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.dispatch(ready_work(workspace_id=str(tmp_path)))
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed"
        assert decision.receipt.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is not True

    def test_done_without_artifact_not_completed(self, profiles, receipts, tmp_path):
        adapter = MockAdapter(wait_status="done")
        # artifact deliberately absent
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.dispatch(ready_work(workspace_id=str(tmp_path)))
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed_without_artifact"
        assert decision.metadata.get("artifact_missing") is True
        # must NOT be accepted as plain completed
        assert decision.receipt.terminal_outcome == "completed_without_artifact"

    def test_unknown_with_artifact_promoted(self, profiles, receipts, tmp_path):
        # pane-send style observation (unknown, non-terminal) + artifact exists
        adapter = MockAdapter(wait_status="unknown")
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("ok", encoding="utf-8")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.dispatch(ready_work(workspace_id=str(tmp_path)))
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is True


# ---------------------------------------------------------------------------
# (b) pane-send wait_agent + _outcome_from_observation never invent "completed"
# ---------------------------------------------------------------------------
class TestPaneSendNoFabrication:
    def test_wait_unknown_is_not_completed(self, profiles, receipts):
        adapter = MockAdapter(wait_status="unknown")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work())
        assert decision.dispatched is True
        # the observation-level terminal stays "unknown" when no artifact gate
        assert decision.terminal_outcome == "unknown"
        assert decision.terminal_outcome != "completed"

    def test_outcome_from_observation_unknown_never_completed(self):
        outcome = APCBDispatcher._outcome_from_observation
        assert outcome(_Obs("unknown")) == "unknown"
        assert outcome(_Obs("unknown", error="no lifecycle")) == "unknown"
        assert outcome(_Obs("done")) == "completed"
        assert outcome(_Obs("blocked")) == "blocked"
        assert outcome(_Obs("terminated")) == "blocked"
        assert outcome(_Obs("idle")) == "unknown"


# ---------------------------------------------------------------------------
# (c) reconcile emits reconcile_artifact_found; receipt is NOT rewritten
# ---------------------------------------------------------------------------
class TestReconcileArtifactFound:
    def _terminal_receipt(self, outcome="unknown", attempt=1):
        return BridgeExecutionReceipt(
            work_id="WORK-PCP-003",
            attempt_number=attempt,
            principal_id="qwen",
            mission_id="MISSION-PCP-001",
            state=ExecutionReceiptStatus.TERMINAL,
            terminal_outcome=outcome,
            herdr_execution_ref="herdr://pane/w7:p3",
            observed_at="2026-08-13T00:00:00Z",
        )

    def test_unknown_terminal_artifact_promotes(self, profiles, receipts, tmp_path):
        receipts.persist(self._terminal_receipt(outcome="unknown"))
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("ok", encoding="utf-8")
        adapter = MockAdapter(wait_status="unknown")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.reconcile(ready_work(workspace_id=str(tmp_path)))
        assert decision.status == "promoted"
        assert decision.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is True
        # append-only: the original terminal receipt is NOT rewritten
        original = receipts.get_by_components("WORK-PCP-003", 1, "qwen")
        assert original.terminal_outcome == "unknown"

    def test_failed_terminal_artifact_promotes(self, profiles, receipts, tmp_path):
        receipts.persist(self._terminal_receipt(outcome="failed"))
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("ok", encoding="utf-8")
        adapter = MockAdapter(wait_status="failed")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.reconcile(ready_work(workspace_id=str(tmp_path)))
        assert decision.status == "promoted"
        assert decision.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is True
        # K2: exactly one terminal per tuple — the failed terminal is untouched
        original = receipts.get_by_components("WORK-PCP-003", 1, "qwen")
        assert original.terminal_outcome == "failed"

    def test_no_artifact_no_promotion(self, profiles, receipts, tmp_path):
        # artifact absent -> reconcile falls through to observation path
        receipts.persist(self._terminal_receipt(outcome="unknown"))
        adapter = MockAdapter(wait_status="unknown")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.reconcile(ready_work(workspace_id=str(tmp_path)))
        assert decision.status != "promoted"
        assert decision.metadata.get("reconcile_artifact_found") is not True


# ---------------------------------------------------------------------------
# (a) aether_state_observer wired: reconcile respects canonical mission state
# ---------------------------------------------------------------------------
class TestMissionStateObserver:
    def test_mission_terminal_stops_reconcile(self, profiles, receipts):
        receipts.persist(
            BridgeExecutionReceipt(
                work_id="WORK-PCP-003",
                attempt_number=1,
                principal_id="qwen",
                mission_id="MISSION-PCP-001",
                state=ExecutionReceiptStatus.PROMPTED,
                herdr_execution_ref="herdr://pane/w7:p3",
                observed_at="2026-08-13T00:00:00Z",
            )
        )
        adapter = MockAdapter(wait_status="done")
        dispatcher = make_dispatcher(
            profiles, receipts, adapter, mission_state="failed"
        )
        decision = dispatcher.reconcile(ready_work())
        assert decision.status == "terminal"
        assert decision.terminal_outcome == "stopped"
        assert "aether mission state=failed" in " ".join(decision.diagnostic)

    def test_observer_none_defaults_unknown(self, profiles, receipts):
        # no observer wired -> default "unknown" (observation-level, no invention)
        receipts.persist(
            BridgeExecutionReceipt(
                work_id="WORK-PCP-003",
                attempt_number=1,
                principal_id="qwen",
                mission_id="MISSION-PCP-001",
                state=ExecutionReceiptStatus.PROMPTED,
                herdr_execution_ref="herdr://pane/w7:p3",
                observed_at="2026-08-13T00:00:00Z",
            )
        )
        adapter = MockAdapter(wait_status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.reconcile(ready_work())
        # mission not seen as terminal -> proceeds to promotion (not stopped)
        assert decision.status == "promoted"
        assert decision.terminal_outcome == "completed"


# ---------------------------------------------------------------------------
# (d) F-03: mission-state check BEFORE artifact-promotion (contract §11 3-4)
# ---------------------------------------------------------------------------
class TestMissionStateBeforeArtifact:
    def test_mission_terminal_artifact_stale_not_promoted(self, profiles, receipts, tmp_path):
        # unknown terminal receipt + artifact exists + mission terminal ->
        # must STOP, never promote a stale artifact (F-03).
        receipts.persist(self._terminal_receipt(outcome="unknown"))
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("ok", encoding="utf-8")
        adapter = MockAdapter(wait_status="unknown")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            mission_state="completed",
            artifact_verify=lambda work: (Path(work.workspace_id) / "WORK-PCP-003.md").is_file(),
        )
        decision = dispatcher.reconcile(ready_work(workspace_id=str(tmp_path)))
        assert decision.status == "terminal"
        assert decision.terminal_outcome == "stopped"
        assert "aether mission state=completed" in " ".join(decision.diagnostic)

    def test_mission_terminal_receipt_definitive_no_second_terminal(self, profiles, receipts):
        # mission terminal + receipt already definitive (failed) -> NO
        # DuplicateTerminalError, status=terminal with existing outcome.
        receipts.persist(self._terminal_receipt(outcome="failed"))
        adapter = MockAdapter(wait_status="failed")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            mission_state="failed",
            artifact_verify=lambda work: False,
        )
        decision = dispatcher.reconcile(ready_work())
        assert decision.status == "terminal"
        assert decision.terminal_outcome == "failed"
        # exactly one terminal remains on disk — no second terminal written
        assert len(receipts.notes()) == 0

    def _terminal_receipt(self, outcome="unknown", attempt=1):
        return BridgeExecutionReceipt(
            work_id="WORK-PCP-003",
            attempt_number=attempt,
            principal_id="qwen",
            mission_id="MISSION-PCP-001",
            state=ExecutionReceiptStatus.TERMINAL,
            terminal_outcome=outcome,
            herdr_execution_ref="herdr://pane/w7:p3",
            observed_at="2026-08-13T00:00:00Z",
        )


# ---------------------------------------------------------------------------
# (e) F-01/F-02: artifact envelope must match the work item
# ---------------------------------------------------------------------------
from aether.apcb.cli import _build_artifact_verify


def _envelope_artifact_text(attempt=1, work_id="WORK-PCP-003", principal_id="qwen"):
    return (
        "protocol: aether.apcb.task.v1\n"
        f"work_id: {work_id}\n"
        "mission_id: MISSION-PCP-001\n"
        f"principal_id: {principal_id}\n"
        f"attempt: {attempt}\n"
        "\n"
        "## Body\n"
        "implemented artifact authority."
    )


class TestArtifactEnvelope:
    def test_placeholder_1byte_no_envelope_not_completed(self, profiles, receipts, tmp_path):
        # F-01: a 1-byte placeholder without the canonical envelope must NOT be
        # accepted as the deliverable.
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text("x", encoding="utf-8")
        adapter = MockAdapter(wait_status="done")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=_build_artifact_verify("WORK-PCP-003.md"),
        )
        decision = dispatcher.dispatch(ready_work(workspace_id=str(tmp_path)))
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed_without_artifact"
        assert decision.metadata.get("artifact_missing") is True

    def test_artifact_stale_attempt_mismatch_rejected(self, profiles, receipts, tmp_path):
        # F-02: artifact whose envelope says attempt 1 while the work item is
        # attempt 2 (stale from a prior attempt in the same workspace) -> reject.
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text(_envelope_artifact_text(attempt=1), encoding="utf-8")
        adapter = MockAdapter(wait_status="done")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=_build_artifact_verify("WORK-PCP-003.md"),
        )
        decision = dispatcher.dispatch(
            ready_work(workspace_id=str(tmp_path), attempt_number=2)
        )
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed_without_artifact"
        assert decision.metadata.get("artifact_missing") is True

    def test_artifact_envelope_correct_completed(self, profiles, receipts, tmp_path):
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text(_envelope_artifact_text(attempt=1), encoding="utf-8")
        adapter = MockAdapter(wait_status="done")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=_build_artifact_verify("WORK-PCP-003.md"),
        )
        decision = dispatcher.dispatch(ready_work(workspace_id=str(tmp_path)))
        assert decision.dispatched is True
        assert decision.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is not True

    def test_reconcile_stale_artifact_not_promoted(self, profiles, receipts, tmp_path):
        # stale envelope (attempt mismatch) on reconcile -> NOT promoted.
        receipts.persist(
            BridgeExecutionReceipt(
                work_id="WORK-PCP-003",
                attempt_number=2,
                principal_id="qwen",
                mission_id="MISSION-PCP-001",
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome="unknown",
                herdr_execution_ref="herdr://pane/w7:p3",
                observed_at="2026-08-13T00:00:00Z",
            )
        )
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text(_envelope_artifact_text(attempt=1), encoding="utf-8")
        adapter = MockAdapter(wait_status="unknown")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=_build_artifact_verify("WORK-PCP-003.md"),
        )
        decision = dispatcher.reconcile(
            ready_work(workspace_id=str(tmp_path), attempt_number=2)
        )
        assert decision.status != "promoted"
        assert decision.metadata.get("reconcile_artifact_found") is not True


# ---------------------------------------------------------------------------
# (f) F-04: reconcile note is durable on disk (not only DispatchDecision)
# ---------------------------------------------------------------------------
class TestReconcileNoteDurable:
    def test_reconcile_promote_writes_durable_note(self, profiles, receipts, tmp_path):
        receipts.persist(
            BridgeExecutionReceipt(
                work_id="WORK-PCP-003",
                attempt_number=1,
                principal_id="qwen",
                mission_id="MISSION-PCP-001",
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome="failed",
                herdr_execution_ref="herdr://pane/w7:p3",
                observed_at="2026-08-13T00:00:00Z",
            )
        )
        artifact = tmp_path / "WORK-PCP-003.md"
        artifact.write_text(_envelope_artifact_text(attempt=1), encoding="utf-8")
        adapter = MockAdapter(wait_status="failed")
        dispatcher = make_dispatcher(
            profiles,
            receipts,
            adapter,
            artifact_verify=_build_artifact_verify("WORK-PCP-003.md"),
        )
        decision = dispatcher.reconcile(ready_work(workspace_id=str(tmp_path)))
        assert decision.status == "promoted"
        assert decision.terminal_outcome == "completed"
        assert decision.metadata.get("reconcile_artifact_found") is True
        # F-04: note must be reconstructable from disk (survive restart).
        assert receipts.notes_path.exists()
        notes = receipts.notes()
        assert len(notes) == 1
        note = notes[0]
        assert note["note_type"] == "reconcile_artifact_found"
        assert note["work_id"] == "WORK-PCP-003"
        assert note["principal_id"] == "qwen"
        assert note["attempt_number"] == 1
        assert note["prior_terminal_outcome"] == "failed"
        assert note["new_terminal_outcome"] == "completed"
        assert note["artifact_found"] is True
        # restart-safe: a fresh store over the same files still sees the note
        fresh = ReceiptStore(receipts.path)
        assert len(fresh.notes()) == 1
        assert fresh.notes()[0]["note_type"] == "reconcile_artifact_found"

    def test_notes_empty_when_no_reconcile(self, profiles, receipts):
        # no reconcile-promote -> notes file absent / empty list
        assert receipts.notes() == []
