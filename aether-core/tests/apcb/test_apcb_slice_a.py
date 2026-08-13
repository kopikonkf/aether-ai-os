"""APCB Slice A tests — contracts/config only, no dispatch logic."""
from __future__ import annotations

import pytest

from aether.apcb import (
    BridgeExecutionReceipt,
    DispatchEligibility,
    ExecutionReceiptStatus,
    PrincipalHandoff,
    PromptEnvelope,
    execution_receipt_key,
    load_principal_profiles,
)
from aether.apcb.profiles import PrincipalRuntimeProfiles


# ---------------------------------------------------------------------------
# Principal profile registry (contract section 7)
# ---------------------------------------------------------------------------

class TestPrincipalProfileRegistry:
    def test_loads_canonical_yaml(self):
        reg = load_principal_profiles()
        assert isinstance(reg, PrincipalRuntimeProfiles)
        assert "chatgpt" in reg.principals
        assert "claude" in reg.principals
        assert "qwen" in reg.principals

    def test_idempotency_key_derived_from_yaml(self):
        reg = load_principal_profiles()
        assert reg.dispatch_idempotency_key == (
            "work_id",
            "attempt_number",
            "principal_id",
        )

    def test_capability_lookup(self):
        reg = load_principal_profiles()
        assert reg.principal_can("claude", "architecture_review")
        assert not reg.principal_can("claude", "coding")

    def test_execution_profile_mapping(self):
        reg = load_principal_profiles()
        p = reg.get_principal("qwen")
        assert p is not None
        assert "herdr:qwen" in p.execution_profiles
        ep = reg.get_execution_profile("herdr:qwen")
        assert ep is not None
        assert ep.herdr_agent_kind == "qwen"

    def test_role_never_implies_mutation_authority(self):
        reg = load_principal_profiles()
        for pid, p in reg.principals.items():
            assert p.mutation_authority is False, f"principal {pid} must not self-grant mutation"

    def test_fail_closed_on_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PrincipalRuntimeProfiles(tmp_path / "missing.yaml")

    def test_fail_closed_on_bad_principals_shape(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("principals: not-a-mapping\n", encoding="utf-8")
        with pytest.raises(ValueError):
            PrincipalRuntimeProfiles(bad)


# ---------------------------------------------------------------------------
# Durable coordination identity (contract section 5)
# ---------------------------------------------------------------------------

class TestIdempotencyKey:
    def test_tuple_shape(self):
        key = execution_receipt_key("WORK-1", 2, "qwen")
        assert key.as_tuple() == ("WORK-1", 2, "qwen")

    def test_receipt_key_matches_idempotency(self):
        receipt = BridgeExecutionReceipt(
            work_id="WORK-1", attempt_number=1, principal_id="claude", mission_id="MISSION-1"
        )
        assert receipt.idempotency_key.as_tuple() == ("WORK-1", 1, "claude")

    def test_bridge_request_and_correlation_ids(self):
        r1 = BridgeExecutionReceipt(work_id="W", attempt_number=1, principal_id="p", mission_id="m")
        r2 = BridgeExecutionReceipt(work_id="W", attempt_number=1, principal_id="p", mission_id="m")
        assert r1.bridge_request_id != r2.bridge_request_id


# ---------------------------------------------------------------------------
# Dispatch eligibility (contract section 4)
# ---------------------------------------------------------------------------

class TestDispatchEligibility:
    def test_all_true_is_dispatchable(self):
        e = DispatchEligibility(
            authorized=True,
            execution_ready=True,
            principal_assigned=True,
            profile_enabled=True,
            capability_match=True,
            workspace_bound=True,
            no_active_attempt=True,
            not_awaiting_approval=True,
        )
        assert bool(e) is True
        assert e.blockers() == []

    def test_single_false_blocks(self):
        e = DispatchEligibility(
            authorized=True,
            execution_ready=True,
            principal_assigned=True,
            profile_enabled=True,
            capability_match=True,
            workspace_bound=False,  # missing workspace binding
            no_active_attempt=True,
            not_awaiting_approval=True,
        )
        assert bool(e) is False
        assert e.blockers() == ["workspace_bound"]

    def test_awaiting_approval_never_dispatchable(self):
        e = DispatchEligibility(
            authorized=True,
            execution_ready=True,
            principal_assigned=True,
            profile_enabled=True,
            capability_match=True,
            workspace_bound=True,
            no_active_attempt=True,
            not_awaiting_approval=False,
        )
        assert bool(e) is False
        assert "not_awaiting_approval" in e.blockers()


# ---------------------------------------------------------------------------
# State machine constants (contract section 6)
# ---------------------------------------------------------------------------

class TestExecutionStates:
    def test_apcb_local_sequence(self):
        expected = [
            ExecutionReceiptStatus.DISCOVERED,
            ExecutionReceiptStatus.CLAIM_REQUESTED,
            ExecutionReceiptStatus.CLAIMED,
            ExecutionReceiptStatus.HERDR_ATTACHED,
            ExecutionReceiptStatus.PROMPTED,
            ExecutionReceiptStatus.OBSERVING,
            ExecutionReceiptStatus.RECONCILING,
            ExecutionReceiptStatus.TERMINAL,
        ]
        assert list(ExecutionReceiptStatus) == expected

    def test_receipt_terminal(self):
        r = BridgeExecutionReceipt(
            work_id="W", attempt_number=1, principal_id="p", mission_id="m",
            state=ExecutionReceiptStatus.TERMINAL,
        )
        assert r.is_terminal()


# ---------------------------------------------------------------------------
# Prompt envelope (contract section 9) and handoff (section 10)
# ---------------------------------------------------------------------------

class TestPromptEnvelope:
    def test_protocol_and_fields(self):
        env = PromptEnvelope(
            work_id="WORK-1",
            mission_id="MISSION-1",
            principal_id="qwen",
            objective="Implement from Claude artifact",
            acceptance_criteria=["pytest green"],
            relevant_artifacts=["ART-1"],
        )
        d = env.to_dict()
        assert d["protocol"] == "aether.apcb.task.v1"
        assert d["work_id"] == "WORK-1"
        assert d["acceptance_criteria"] == ["pytest green"]
        assert d["relevant_artifacts"] == ["ART-1"]

    def test_no_forwarded_transcript_field(self):
        # Contract: APCB never forwards another principal's full transcript.
        env = PromptEnvelope(work_id="W", mission_id="M", principal_id="qwen")
        d = env.to_dict()
        assert "transcript" not in d
        assert "conversation" not in d


class TestPrincipalHandoff:
    def test_handoff_is_aether_artifact(self):
        h = PrincipalHandoff(
            from_principal="claude",
            to_principal="qwen",
            work_id="WORK-1",
            mission_id="MISSION-1",
            summary="architecture artifact published",
            artifacts=["ART-1"],
        )
        d = h.to_dict()
        assert d["type"] == "principal_handoff"
        assert d["from_principal"] == "claude"
        assert d["to_principal"] == "qwen"
        assert d["correlation_id"]

    def test_default_correlation_id_unique(self):
        a = PrincipalHandoff(from_principal="c", to_principal="q", work_id="w", mission_id="m")
        b = PrincipalHandoff(from_principal="c", to_principal="q", work_id="w", mission_id="m")
        assert a.correlation_id != b.correlation_id
