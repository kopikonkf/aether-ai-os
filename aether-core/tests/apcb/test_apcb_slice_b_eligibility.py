"""APCB Slice B — DispatchEligibility all-or-nothing gate (contract section 4).

A work item is dispatchable only when ALL eight conditions are true. APCB
must never promote a blocked or approval-waiting step into Herdr execution.
"""
from __future__ import annotations

import pytest

from aether.apcb.contracts import DispatchEligibility
from aether.apcb.eligibility import EligibilityEvaluator, WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.apcb.receipt_store import ReceiptStore


@pytest.fixture
def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


@pytest.fixture
def receipts(tmp_path) -> ReceiptStore:
    return ReceiptStore(tmp_path / "receipts.jsonl")


@pytest.fixture
def evaluator(profiles, receipts) -> EligibilityEvaluator:
    return EligibilityEvaluator(profiles, receipts)


def fully_ready(**overrides) -> WorkItemView:
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
    )
    return WorkItemView(**{**view.__dict__, **overrides})


class TestEligibilityAllOrNothing:
    def test_all_true_dispatchable(self, evaluator):
        e = evaluator.evaluate(fully_ready())
        assert bool(e) is True
        assert e.blockers() == []

    def test_not_authorized_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(authorized=False))
        assert bool(e) is False
        assert "authorized" in e.blockers()

    def test_not_execution_ready_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(execution_ready=False))
        assert bool(e) is False
        assert "execution_ready" in e.blockers()

    def test_no_principal_assigned_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(principal_id=""))
        assert bool(e) is False
        assert "principal_assigned" in e.blockers()

    def test_unknown_principal_no_profile_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(principal_id="nobody"))
        assert bool(e) is False
        assert "profile_enabled" in e.blockers()

    def test_capability_mismatch_blocks(self, evaluator):
        # qwen cannot do architecture_review
        e = evaluator.evaluate(
            fully_ready(required_capabilities=("architecture_review",))
        )
        assert bool(e) is False
        assert "capability_match" in e.blockers()

    def test_no_workspace_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(workspace_id=""))
        assert bool(e) is False
        assert "workspace_bound" in e.blockers()

    def test_active_attempt_blocks(self, evaluator, receipts):
        receipts.persist(
            __import__("aether.apcb.contracts", fromlist=["BridgeExecutionReceipt"])
            .BridgeExecutionReceipt(
                work_id="WORK-1",
                attempt_number=1,
                principal_id="qwen",
                mission_id="MISSION-1",
                state=__import__("aether.apcb.contracts", fromlist=["ExecutionReceiptStatus"])
                .ExecutionReceiptStatus.CLAIMED,
            )
        )
        e = evaluator.evaluate(fully_ready())
        assert bool(e) is False
        assert "no_active_attempt" in e.blockers()

    def test_terminal_attempt_does_not_block(self, evaluator, receipts):
        from aether.apcb.contracts import BridgeExecutionReceipt, ExecutionReceiptStatus

        receipts.persist(
            BridgeExecutionReceipt(
                work_id="WORK-1",
                attempt_number=1,
                principal_id="qwen",
                mission_id="MISSION-1",
                state=ExecutionReceiptStatus.TERMINAL,
            )
        )
        # terminal receipt -> new attempt is allowed
        e = evaluator.evaluate(fully_ready(attempt_number=2))
        assert "no_active_attempt" not in e.blockers()

    def test_awaiting_approval_blocks(self, evaluator):
        e = evaluator.evaluate(fully_ready(awaiting_approval=True))
        assert bool(e) is False
        assert "not_awaiting_approval" in e.blockers()

    def test_all_blockers_listed(self, evaluator):
        e = evaluator.evaluate(
            WorkItemView(
                work_id="WORK-1",
                mission_id="MISSION-1",
                principal_id="",
                required_capabilities=(),
                workspace_id="",
                authorized=False,
                execution_ready=False,
                awaiting_approval=True,
                attempt_number=1,
            )
        )
        assert bool(e) is False
        blockers = e.blockers()
        assert "authorized" in blockers
        assert "execution_ready" in blockers
        assert "principal_assigned" in blockers
        assert "workspace_bound" in blockers
        assert "not_awaiting_approval" in blockers


class TestEligibilityDictInput:
    def test_evaluate_dict_maps_fields(self, evaluator, receipts):
        work = {
            "work_item_id": "WORK-9",
            "mission_id": "MISSION-9",
            "agent": "qwen",
            "required_capabilities": ["coding"],
            "workspace_id": "workspace://w",
            "execution_ready": True,
            "execution_authorized": True,
        }
        e = evaluator.evaluate_dict(work)
        assert bool(e) is True

    def test_evaluate_dict_detects_pending_approval(self, evaluator):
        work = {
            "work_item_id": "WORK-9",
            "mission_id": "MISSION-9",
            "agent": "qwen",
            "required_capabilities": ["coding"],
            "workspace_id": "workspace://w",
            "execution_ready": True,
            "execution_authorized": True,
            "pending_approval": True,
        }
        e = evaluator.evaluate_dict(work)
        assert bool(e) is False
        assert "not_awaiting_approval" in e.blockers()
