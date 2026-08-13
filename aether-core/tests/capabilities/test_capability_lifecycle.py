"""Deterministic tests for the capability lifecycle state machine (ADR-0055 P4)."""
from __future__ import annotations

import json
import re

import pytest

from aether.capabilities.lifecycle import (
    KNOWN_MUTATION_SURFACES,
    REQUIRED_EVIDENCE,
    SCHEMA,
    STAGES,
    CapabilityLifecycle,
    CapabilityLifecycleBlocked,
    CapabilityLifecycleRecord,
    MUTATION_SURFACE_LIVING_MCP,
    next_stage,
    stage_index,
    validate_evidence,
    validate_principal,
    validate_surface,
)


def full_evidence(stage: str) -> dict[str, bool]:
    """Synthetic evidence markers satisfying the stage requirements."""
    return {key: True for key in REQUIRED_EVIDENCE[stage]}


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------

class TestContractShape:
    def test_schema_constant(self):
        assert SCHEMA == "aether.capability-lifecycle.v1"

    def test_stage_chain_exact(self):
        assert STAGES == ("implemented", "wired", "conformed", "active", "founder-proven")

    def test_next_stage_monotonic(self):
        assert next_stage("implemented") == "wired"
        assert next_stage("wired") == "conformed"
        assert next_stage("conformed") == "active"
        assert next_stage("active") == "founder-proven"
        assert next_stage("founder-proven") is None

    def test_evidence_required_per_stage(self):
        for stage in STAGES:
            ok, blockers = validate_evidence(stage, {})
            assert not ok
            assert blockers, f"stage {stage} must require evidence"

    def test_known_mutation_surface(self):
        assert MUTATION_SURFACE_LIVING_MCP in KNOWN_MUTATION_SURFACES

    def test_validate_principal_rejects_unsafe(self):
        with pytest.raises(ValueError):
            validate_principal("has space")
        with pytest.raises(ValueError):
            validate_principal("") or validate_principal(None)  # type: ignore[arg-type]

    def test_validate_surface_rejects_unknown(self):
        with pytest.raises(ValueError):
            validate_surface("made-up.surface")


# ---------------------------------------------------------------------------
# Pure transitions (no persistence)
# ---------------------------------------------------------------------------

class TestTransitions:
    def test_first_principal_reaches_founder_proven(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        stages = STAGES[1:]
        for i, stage in enumerate(stages):
            record = lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
            assert record.stage == stage
            assert record.founder_proven is (stage == "founder-proven")
            assert len(record.transitions) == i + 1

    def test_transition_must_be_consecutive(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        with pytest.raises(CapabilityLifecycleBlocked) as exc:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage="conformed",
                evidence=full_evidence("conformed"),
            )
        assert any("expected stage 'wired'" in b for b in exc.value.blockers)

    def test_missing_evidence_blocks(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        with pytest.raises(CapabilityLifecycleBlocked) as exc:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage="wired",
                evidence={"runtime_constructed": True},  # missing path_reachable
            )
        assert any("missing evidence" in b for b in exc.value.blockers)

    def test_same_stage_blocks(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        with pytest.raises(CapabilityLifecycleBlocked):
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage="implemented",
                evidence=full_evidence("implemented"),
            )

    def test_unknown_stage_blocks(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        with pytest.raises(CapabilityLifecycleBlocked):
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage="bogus",
                evidence={},
            )

    def test_evidence_stored_as_markers_only(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        record = lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="chatgpt",
            to_stage="wired",
            evidence={"runtime_constructed": True, "path_reachable": "https://aethers.my.id/mcp"},
        )
        raw = json.loads(tmp_path.joinpath("log.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert raw["evidence"] == {"runtime_constructed": True, "path_reachable": True}


# ---------------------------------------------------------------------------
# Single-principal gate (ADR-0055 P4)
# ---------------------------------------------------------------------------

class TestSinglePrincipalGate:
    def _first_principal_proven(self, tmp_path) -> CapabilityLifecycle:
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        for stage in STAGES[1:]:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
        return lc

    def test_second_principal_blocked_before_first_proven(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        # first principal reaches ACTIVE only
        for stage in ("wired", "conformed", "active"):
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
        # second principal cannot become ACTIVE
        lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="claude",
            to_stage="wired",
            evidence=full_evidence("wired"),
        )
        # conformed is observation-level (canary passed) — not authorization
        lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="claude",
            to_stage="conformed",
            evidence=full_evidence("conformed"),
        )
        with pytest.raises(CapabilityLifecycleBlocked) as exc3:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="claude",
                to_stage="active",
                evidence=full_evidence("active"),
            )
        assert any("single-principal gate" in b for b in exc3.value.blockers)

    def test_second_principal_allowed_after_first_proven(self, tmp_path):
        lc = self._first_principal_proven(tmp_path)
        for stage in ("wired", "conformed", "active"):
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="claude",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
        assert lc.record(MUTATION_SURFACE_LIVING_MCP, "claude").stage == "active"

    def test_second_principal_cannot_also_be_founder_proven(self, tmp_path):
        lc = self._first_principal_proven(tmp_path)
        for stage in ("wired", "conformed", "active"):
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="claude",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
        with pytest.raises(CapabilityLifecycleBlocked) as exc:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="claude",
                to_stage="founder-proven",
                evidence=full_evidence("founder-proven"),
            )
        assert any("already founder-proven" in b for b in exc.value.blockers)

    def test_surface_state_reports_founder(self, tmp_path):
        lc = self._first_principal_proven(tmp_path)
        state = lc.surface_state(MUTATION_SURFACE_LIVING_MCP)
        assert state["founder_proven_principal"] == "chatgpt"
        assert state["schema"] == SCHEMA


# ---------------------------------------------------------------------------
# Persistence round-trip (recompute from log, never trust a latest file)
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_round_trip_rebuilds_state(self, tmp_path):
        path = tmp_path / "lifecycle" / "log.jsonl"
        lc = CapabilityLifecycle(path)
        for stage in STAGES[1:]:
            lc.advance(
                surface=MUTATION_SURFACE_LIVING_MCP,
                principal_id="chatgpt",
                to_stage=stage,
                evidence=full_evidence(stage),
            )
        rebuilt = CapabilityLifecycle(path)
        record = rebuilt.record(MUTATION_SURFACE_LIVING_MCP, "chatgpt")
        assert record is not None
        assert record.stage == "founder-proven"
        assert len(record.transitions) == 4
        assert record.transitions[0].from_stage == "implemented"
        assert record.transitions[-1].to_stage == "founder-proven"

    def test_corrupt_line_skipped(self, tmp_path):
        path = tmp_path / "log.jsonl"
        path.write_text("not-json\n", encoding="utf-8")
        lc = CapabilityLifecycle(path)
        assert lc.records() == []

    def test_no_log_path_is_in_memory_only(self):
        lc = CapabilityLifecycle()
        lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="chatgpt",
            to_stage="wired",
            evidence=full_evidence("wired"),
        )
        assert lc.record(MUTATION_SURFACE_LIVING_MCP, "chatgpt").stage == "wired"

    def test_note_sanitized(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        record = lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="chatgpt",
            to_stage="wired",
            evidence=full_evidence("wired"),
            note="first line\nsecond line\rmore",
        )
        assert "\n" not in record.transitions[-1].note
        assert "\r" not in record.transitions[-1].note


# ---------------------------------------------------------------------------
# Manifest integration contract (read-only)
# ---------------------------------------------------------------------------

class TestManifestContract:
    def test_record_to_dict_has_no_secret_fields(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        record = lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="chatgpt",
            to_stage="wired",
            evidence=full_evidence("wired"),
        )
        d = record.to_dict()
        assert set(d) == {"schema", "surface", "principal_id", "stage", "updated_at", "transitions", "evidence_keys"}
        for transition in d["transitions"]:
            assert set(transition) == {"surface", "principal_id", "from_stage", "to_stage", "evidence_ids", "ts", "note"}

    def test_evidence_keys_are_stable_ids(self, tmp_path):
        lc = CapabilityLifecycle(tmp_path / "log.jsonl")
        record = lc.advance(
            surface=MUTATION_SURFACE_LIVING_MCP,
            principal_id="chatgpt",
            to_stage="wired",
            evidence=full_evidence("wired"),
        )
        for key in record.evidence:
            assert re.match(r"^[a-z_]+$", key)
