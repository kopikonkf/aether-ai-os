"""APCB governance rules (WORK-5 blockers K2, K3, K4) — deterministic tests.

Covers:
  - K2 terminal uniqueness: a second terminal write for the same
    (work_id, attempt_number, principal_id) raises DuplicateTerminalError; the
    dispatcher short-circuits reconcile on an already-terminal receipt.
  - K3 re-dispatch reconcile gate: a new attempt after a prior terminal attempt
    is rejected unless work metadata carries needs_reconcile or approval_id.
  - K4 pane uniqueness validator: fail-closed when apcb_pane_map.json maps two
    principals to the same pane, or is missing/malformed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aether.apcb import (
    AdapterConformanceStatus,
    APCBDispatcher,
    BridgeExecutionReceipt,
    ConformanceGate,
    ExecutionReceiptStatus,
    PaneUniquenessError,
    ReceiptStore,
    validate_pane_map_unique,
)
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
class RecordingAdapter:
    def __init__(self, status="done"):
        self.status = status
        self.calls: list[str] = []
        self.ensure_agent_ref = "herdr://pane/w7:p3"

    def ensure_agent(self, workspace_ref, principal_id, herdr_agent_kind=None):
        self.calls.append(f"ensure_agent:{principal_id}")
        return self.ensure_agent_ref

    def prompt_agent(self, agent_ref, task_context):
        self.calls.append("prompt_agent")
        return f"{agent_ref}/prompt"

    def wait_agent(self, agent_ref, timeout_seconds):
        self.calls.append("wait_agent")
        return _Obs(self.agent_obs_status(), is_terminal=self.agent_obs_status() in ("done", "blocked"))

    def read_agent(self, agent_ref, limit_bytes=8192):
        self.calls.append("read_agent")
        return "[aether-apcb-test] worker reply"

    def observe_agent(self, agent_ref):
        self.calls.append("observe_agent")
        return _Obs(self.agent_obs_status(), is_terminal=self.agent_obs_status() in ("done", "blocked"))

    def recover_agent(self, agent_ref):
        self.calls.append("recover_agent")
        return self.observe_agent(agent_ref)

    def agent_obs_status(self):
        return self.status


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


def make_dispatcher(profiles, receipts, adapter, status_by_kind=None, mission_state="running"):
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
        execution_profile="herdr:cline",
        metadata={"objective": "governance test"},
    )
    return WorkItemView(**{**view.__dict__, **overrides})


def _terminal_receipt(work_id="WORK-1", attempt=1, principal="qwen", outcome="completed", mission="MISSION-1"):
    return BridgeExecutionReceipt(
        work_id=work_id,
        attempt_number=attempt,
        principal_id=principal,
        mission_id=mission,
        state=ExecutionReceiptStatus.TERMINAL,
        terminal_outcome=outcome,
        observed_at="2026-08-13T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# K2 — terminal uniqueness
# ---------------------------------------------------------------------------
class TestK2TerminalUniqueness:
    def test_duplicate_terminal_rejected(self, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        with pytest.raises(Exception) as exc:
            receipts.persist(_terminal_receipt(outcome="failed"))
        assert "terminal already recorded" in str(exc.value)

    def test_unknown_terminal_can_be_resolved(self, receipts):
        receipts.persist(_terminal_receipt(outcome="unknown"))
        # unknown is not authoritative (K10) -> a definitive terminal may follow
        resolved = receipts.persist(_terminal_receipt(outcome="completed"))
        assert resolved.terminal_outcome == "completed"
        # ... but a second DEFINITIVE terminal is then rejected
        with pytest.raises(Exception):
            receipts.persist(_terminal_receipt(outcome="failed"))

    def test_terminal_then_duplicate_rejected(self, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        # duplicate terminal again -> rejected regardless of outcome
        with pytest.raises(Exception):
            receipts.persist(_terminal_receipt(outcome="blocked"))

    def test_reconcile_short_circuits_already_terminal(self, profiles, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        adapter = RecordingAdapter()
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work(attempt_number=1))
        assert decision.dispatched is False
        assert decision.status == "terminal"
        assert decision.terminal_outcome == "completed"
        assert "already terminal" in " ".join(decision.diagnostic)


# ---------------------------------------------------------------------------
# K3 — re-dispatch reconcile gate
# ---------------------------------------------------------------------------
class TestK3RedispatchReconcileGate:
    def test_redispatch_after_terminal_requires_reconcile(self, profiles, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        adapter = RecordingAdapter()
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        decision = dispatcher.dispatch(ready_work(attempt_number=2))
        assert decision.dispatched is False
        assert decision.status == "rejected"
        assert any("re-dispatch after terminal requires explicit reconcile" in d for d in decision.diagnostic)
        # nothing was dispatched
        assert adapter.calls.count("prompt_agent") == 0

    def test_redispatch_allowed_with_needs_reconcile(self, profiles, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        adapter = RecordingAdapter()
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        work = ready_work(attempt_number=2, metadata={"needs_reconcile": True, "objective": "retry"})
        decision = dispatcher.dispatch(work)
        assert decision.dispatched is True

    def test_redispatch_allowed_with_approval_id(self, profiles, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        adapter = RecordingAdapter()
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        work = ready_work(attempt_number=2, metadata={"approval_id": "ap-xyz", "objective": "retry"})
        decision = dispatcher.dispatch(work)
        assert decision.dispatched is True

    def test_same_attempt_after_terminal_rejected(self, profiles, receipts):
        receipts.persist(_terminal_receipt(outcome="completed"))
        adapter = RecordingAdapter()
        dispatcher = make_dispatcher(profiles, receipts, adapter)
        # same attempt number as the terminal receipt -> reconcile short-circuit
        decision = dispatcher.dispatch(ready_work(attempt_number=1))
        assert decision.dispatched is False
        assert decision.status == "terminal"


# ---------------------------------------------------------------------------
# K4 — pane uniqueness validator
# ---------------------------------------------------------------------------
class TestK4PaneUniqueness:
    def test_unique_panes_pass(self, tmp_path):
        p = tmp_path / "map.json"
        p.write_text(
            json.dumps({"panes": {"claude": "w7:p7", "qwen": "w7:p4", "gemini": "w7:p5"}}),
            encoding="utf-8",
        )
        resolved = validate_pane_map_unique(str(p))
        assert resolved == {"claude": "w7:p7", "qwen": "w7:p4", "gemini": "w7:p5"}

    def test_collision_fail_closed(self, tmp_path):
        p = tmp_path / "map.json"
        p.write_text(
            json.dumps({"panes": {"gemini": "w7:p4", "qwen": "w7:p4"}}),
            encoding="utf-8",
        )
        with pytest.raises(PaneUniquenessError) as exc:
            validate_pane_map_unique(str(p))
        assert "collision" in str(exc.value)

    def test_missing_sovereign_fail_closed(self, tmp_path):
        p = tmp_path / "map.json"
        p.write_text(json.dumps({"panes": {"claude": "w7:p7"}}), encoding="utf-8")
        with pytest.raises(PaneUniquenessError) as exc:
            validate_pane_map_unique(str(p), sovereign_principals={"claude", "qwen", "gemini"})
        assert "missing sovereign" in str(exc.value)

    def test_missing_map_fail_closed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("APCB_HERDR_PANE_MAP", raising=False)
        with pytest.raises(PaneUniquenessError):
            validate_pane_map_unique(str(tmp_path / "nope.json"))
