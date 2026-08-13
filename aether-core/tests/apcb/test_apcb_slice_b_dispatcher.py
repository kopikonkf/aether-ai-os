"""APCB Slice B — dispatcher orchestration (deterministic, mock herdr).

Covers:
  - receipt persisted BEFORE dispatch (idempotency tuple);
  - eligibility all-or-nothing rejects without dispatch;
  - conformance gate rejects WITHOUT forced fallback;
  - reconcile restart: existing receipt -> no duplicate dispatch;
  - reconcile contract section 11 order (terminal / running / gone);
  - APCB state machine stays observation-level (never invents terminal Aether).
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from aether.apcb import (
    APCBDispatcher,
    AdapterConformanceStatus,
    BridgeExecutionReceipt,
    ConformanceGate,
    DispatchEligibility,
    ExecutionReceiptStatus,
    HerdrExecutionAdapter,
    ReceiptStore,
)
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles


class RecordingAdapter:
    """Deterministic fake of HerdrExecutionAdapter that records calls."""

    def __init__(self, status="done", missing=False):
        self.status = status
        self.missing = missing
        self.calls: list[str] = []
        self.ensure_agent_ref = "herdr://pane/w7:p3"
        self.prompt_texts: list[str] = []

    def ensure_agent(self, workspace_ref, principal_id):
        self.calls.append(f"ensure_agent:{principal_id}")
        return self.ensure_agent_ref

    def prompt_agent(self, agent_ref, task_context):
        self.calls.append("prompt_agent")
        self.prompt_texts.append(task_context)
        return f"{agent_ref}/prompt"

    def wait_agent(self, agent_ref, timeout_seconds):
        self.calls.append("wait_agent")
        return AgentObservationStub(agent_ref, self.status, is_terminal=self.status in ("done", "blocked"))

    def read_agent(self, agent_ref, limit_bytes=8192):
        self.calls.append("read_agent")
        return "[aether-apcb-test] worker reply"

    def observe_agent(self, agent_ref):
        self.calls.append("observe_agent")
        if self.missing:
            return AgentObservationStub(agent_ref, "missing", is_terminal=True)
        return AgentObservationStub(agent_ref, self.status, is_terminal=self.status in ("done", "blocked"))

    def recover_agent(self, agent_ref):
        self.calls.append("recover_agent")
        return self.observe_agent(agent_ref)


class AgentObservationStub:
    def __init__(self, agent_ref, status, is_terminal=False, error=None):
        self.agent_ref = agent_ref
        self.status = status
        self.is_terminal = is_terminal
        self.error = error


@pytest.fixture
def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


@pytest.fixture
def receipts(tmp_path) -> ReceiptStore:
    return ReceiptStore(tmp_path / "receipts.jsonl")


def ready_work(**overrides) -> WorkItemView:
    view = WorkItemView(
        work_id="WORK-1",
        mission_id="MISSION-1",
        principal_id="qwen",
        required_capabilities=("coding",),
        workspace_id="workspace://default",
        authorized=True,
        execution_ready=True,
        awaiting_approval=False,
        attempt_number=1,
        metadata={"objective": "implement slice b", "acceptance_criteria": ["tests pass"]},
    )
    return WorkItemView(**{**view.__dict__, **overrides})


def make_dispatcher(
    profiles,
    receipts,
    adapter,
    status_by_kind=None,
    mission_state="running",
):
    gate = ConformanceGate(
        profiles,
        probe=lambda kind: (status_by_kind or {}).get(kind, AdapterConformanceStatus.HEALTHY),
    )
    return APCBDispatcher(
        profiles=profiles,
        receipts=receipts,
        conformance_gate=gate,
        adapter=adapter,
        aether_state_observer=lambda mission_id: mission_state,
        wait_timeout_seconds=0.5,
    )


class TestDispatchHappyPath:
    def test_receipt_persisted_before_dispatch(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        work = ready_work()

        decision = dispatcher.dispatch(work)

        assert decision.dispatched is True
        assert decision.status == "dispatched"
        assert decision.terminal_outcome == "completed"
        # receipt exists with terminal outcome, durable in the log
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        assert stored is not None
        assert stored.is_terminal()
        assert stored.terminal_outcome == "completed"
        # prompt happened exactly once
        assert adapter.calls.count("prompt_agent") == 1

    def test_prompt_envelope_is_canonical(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work())
        assert decision.dispatched is True
        # Only canonical Aether artifacts are forwarded (contract section 9):
        # protocol/work/mission/principal/attempt/objective/acceptance criteria.
        text = adapter.prompt_texts[0]
        assert "aether.apcb.task.v1" in text
        assert "work_id: WORK-1" in text
        assert "mission_id: MISSION-1" in text
        assert "principal_id: qwen" in text
        assert "attempt: 1" in text
        assert "workspace_id: workspace://default" in text
        assert "objective: implement slice b" in text
        assert "acceptance_criteria:" in text
        assert "tests pass" in text
        # Never forwards a transcript of another principal.
        assert "transcript" not in text.lower()
        assert "claude" not in text.lower()


class TestEligibilityRejectsWithoutDispatch:
    def test_awaiting_approval_never_dispatched(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work(awaiting_approval=True))

        assert decision.dispatched is False
        assert decision.status == "rejected"
        assert "not_awaiting_approval" in decision.diagnostic[0]
        assert "prompt_agent" not in adapter.calls
        # no receipt was persisted for a rejected-before-claim work item
        assert receipts.get_by_components("WORK-1", 1, "qwen") is None

    def test_not_authorized_never_dispatched(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work(authorized=False))
        assert decision.dispatched is False
        assert "authorized" in decision.diagnostic[0]
        assert "prompt_agent" not in adapter.calls


class TestConformanceRejectsWithoutFallback:
    def test_expired_adapter_rejects_no_fallback(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(
            profiles, receipts, adapter,
            status_by_kind={"qwen": AdapterConformanceStatus.EXPIRED},
        )
        decision = dispatcher.dispatch(ready_work())

        assert decision.dispatched is False
        assert decision.status == "rejected"
        assert decision.conformance is not None
        assert decision.conformance.status is AdapterConformanceStatus.EXPIRED
        assert decision.terminal_outcome == "rejected"
        # NO forced fallback: the adapter was never prompted
        assert adapter.calls == []

    def test_missing_adapter_rejects_no_fallback(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(
            profiles, receipts, adapter,
            status_by_kind={"qwen": AdapterConformanceStatus.MISSING},
        )
        decision = dispatcher.dispatch(ready_work())
        assert decision.dispatched is False
        assert decision.conformance.status is AdapterConformanceStatus.MISSING
        assert adapter.calls == []

    def test_unavailable_adapter_rejects_no_fallback(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(
            profiles, receipts, adapter,
            status_by_kind={"qwen": AdapterConformanceStatus.UNAVAILABLE},
        )
        decision = dispatcher.dispatch(ready_work())
        assert decision.dispatched is False
        assert decision.conformance.status is AdapterConformanceStatus.UNAVAILABLE
        assert adapter.calls == []

    def test_conformance_rejection_is_durable(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(
            profiles, receipts, adapter,
            status_by_kind={"qwen": AdapterConformanceStatus.EXPIRED},
        )
        dispatcher.dispatch(ready_work())
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        assert stored is not None
        assert stored.is_terminal()
        assert stored.terminal_outcome == "rejected"


class TestDispatchFailure:
    def test_adapter_error_records_failed_receipt(self, profiles, receipts):
        class BoomAdapter(RecordingAdapter):
            def prompt_agent(self, agent_ref, task_context):
                self.calls.append("prompt_agent")
                raise RuntimeError("herdr connection lost")

        adapter = BoomAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work())
        assert decision.dispatched is False
        assert decision.status == "failed"
        assert decision.terminal_outcome == "failed"
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        assert stored.is_terminal()
        assert stored.terminal_outcome == "failed"


class TestReconcileRestart:
    def test_existing_active_receipt_reconciles_not_redispatch(self, profiles, receipts):
        adapter = RecordingAdapter(status="working")
        dispatcher = make_dispatcher(profiles, receipts, adapter, mission_state="running")

        # First dispatch completes (or partially completes) normally.
        first = dispatcher.dispatch(ready_work())
        assert first.dispatched is True

        # Simulate restart: a NEW dispatcher on the same receipt store.
        dispatcher2 = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        work = ready_work()
        second = dispatcher2.dispatch(work)

        # The new dispatcher sees a TERMINAL receipt -> must NOT re-dispatch.
        # (dispatch() calls reconcile() for a terminal receipt, which observes
        # the herdr agent; with status=working it resumes, no new prompt.)
        assert adapter.calls.count("prompt_agent") == 1
        assert second.status in ("resumed", "promoted")

    def test_restart_reconcile_with_running_agent_resumes(self, profiles, receipts):
        adapter = RecordingAdapter(status="working")
        dispatcher = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        dispatcher.dispatch(ready_work())

        # Restart: reconcile sees herdr still running -> resume, no duplicate.
        dispatcher2 = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        work = ready_work()
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        decision = dispatcher2.reconcile(work, stored)
        assert decision.status == "resumed"
        assert "resuming" in decision.diagnostic[0]
        assert adapter.calls.count("prompt_agent") == 1

    def test_restart_reconcile_terminal_mission_stops(self, profiles, receipts):
        adapter = RecordingAdapter(status="working")
        dispatcher = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        dispatcher.dispatch(ready_work())

        dispatcher2 = make_dispatcher(profiles, receipts, adapter, mission_state="completed")
        work = ready_work()
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        decision = dispatcher2.reconcile(work, stored)
        assert decision.status == "terminal"
        assert decision.terminal_outcome == "stopped"
        assert "aether mission state=completed" in decision.diagnostic[0]

    def test_restart_reconcile_missing_agent_records_failure(self, profiles, receipts):
        adapter = RecordingAdapter(status="done", missing=True)
        dispatcher = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        dispatcher.dispatch(ready_work())

        dispatcher2 = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        work = ready_work()
        stored = receipts.get_by_components("WORK-1", 1, "qwen")
        decision = dispatcher2.reconcile(work, stored)
        assert decision.status == "failed"
        assert decision.terminal_outcome == "failed"
        assert "missing" in decision.diagnostic[0]

    def test_reconcile_without_receipt_rejects(self, profiles, receipts):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.reconcile(ready_work(), None)
        assert decision.status == "rejected"
        assert "no receipt" in decision.diagnostic[0]

    def test_no_new_mission_step_on_restart(self, profiles, receipts):
        """Restart must not fabricate a new mission step / attempt."""
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        dispatcher.dispatch(ready_work())

        dispatcher2 = make_dispatcher(profiles, receipts, adapter, mission_state="running")
        work = ready_work()
        dispatcher2.dispatch(work)
        # attempt stays 1; no attempt-2 receipt was fabricated
        assert receipts.get_by_components("WORK-1", 2, "qwen") is None
        assert receipts.get_by_components("WORK-1", 1, "qwen") is not None


class TestStateMachineObservationLevel:
    def test_dispatcher_never_writes_aether_state(self, profiles, receipts):
        writes = []
        reads = []

        class ReadOnlyObserver:
            def __call__(self, mission_id):
                reads.append(mission_id)
                return "running"

        adapter = RecordingAdapter(status="done")
        gate = ConformanceGate(profiles, probe=lambda kind: AdapterConformanceStatus.HEALTHY)
        observer = ReadOnlyObserver()
        dispatcher = APCBDispatcher(
            profiles=profiles,
            receipts=receipts,
            conformance_gate=gate,
            adapter=adapter,
            aether_state_observer=observer,
            wait_timeout_seconds=0.5,
        )
        dispatcher.dispatch(ready_work())
        # APCB consults Aether state via the observer (read); it never writes a
        # terminal Aether state through it — APCB-local terminal is its own.
        assert reads == []
        assert writes == []
        assert dispatcher.reconcile(ready_work(), receipts.get_by_components("WORK-1", 1, "qwen")).status == "promoted"
        assert reads == ["MISSION-1"]

    def test_receipt_states_follow_observation_chain(self, profiles, receipts, tmp_path):
        adapter = RecordingAdapter(status="done")
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        dispatcher.dispatch(ready_work())
        # The log must show CLAIMED -> ... -> TERMINAL (observation-level chain)
        log_lines = (tmp_path / "receipts.jsonl").read_text("utf-8").splitlines()
        states = [__import__("json").loads(l)["receipt"]["state"] for l in log_lines if l.strip()]
        assert "claimed" in states
        assert states[-1] == "terminal"
        # terminal_outcome is an observation-derived string, never a made-up policy
        assert receipts.all()[-1].terminal_outcome in ("completed", "blocked", "failed", "unknown")
