"""MISSION-PCP-002 WORK-4 — artifact_verify live default (ADR-0057).

Tests for the canonical mission artifact-authority path:
  - build_canonical_work_mapper carries mission_expected_artifact in work.metadata
  - build_expected_artifact_from_criteria derives a filename hint from criteria
  - build_mission_artifact_verify gates a "completed" terminal on the artifact
    existing in the workspace with a matching canonical envelope (reuses
    aether.apcb.cli.parse_artifact_envelope)
  - the executor accepts the artifact_verify param (backward compatible).

Deterministic: real files in tmp_path, no live herdr / no dispatch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aether.apcb.dispatcher import DispatchDecision
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.missions.apcb_executor import ApcbMissionActionExecutor
from aether.missions.canonical_mapper import (
    build_canonical_work_mapper,
    build_expected_artifact_from_criteria,
    build_mission_artifact_verify,
)


def profiles() -> PrincipalRuntimeProfiles:
    return PrincipalRuntimeProfiles()


def proposal(**metadata: Any) -> ActionProposal:
    return ActionProposal(
        target=ActionTarget.RUNTIME,
        operation="implement",
        required_scopes=(ActionScope.EXECUTE,),
        reason="Bounded step.",
        risk=ActionRisk.LOW,
        reversible=True,
        metadata=metadata,
    )


def ready_work(tmp_path: Path, *, workspace: str | None = None) -> WorkItemView:
    return WorkItemView(
        work_id="WORK-PCP-002",
        mission_id="MISSION-PCP-002",
        principal_id="qwen",
        required_capabilities=("coding",),
        workspace_id=workspace or str(tmp_path),
        authorized=True,
        execution_ready=True,
        awaiting_approval=False,
        attempt_number=1,
        execution_profile="herdr:cline",
        metadata={},
    )


def envelope_text(work_id="WORK-PCP-002", principal_id="qwen", attempt=1) -> str:
    return (
        "protocol: aether.apcb.task.v1\n"
        f"work_id: {work_id}\n"
        "mission_id: MISSION-PCP-002\n"
        f"principal_id: {principal_id}\n"
        f"attempt: {attempt}\n"
        "\n"
        "## Body\n"
        "implemented the bounded step."
    )


# ---------------------------------------------------------------------------
# canonical mapper carries mission_expected_artifact
# ---------------------------------------------------------------------------
def test_canonical_mapper_carries_expected_artifact():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(
        mission_principal_id="qwen",
        mission_execution_profile="herdr:cline",
        mission_expected_artifact="WORK-PCP-002.md",
    ), attempt=1)
    assert work.metadata.get("mission_expected_artifact") == "WORK-PCP-002.md"


def test_canonical_mapper_no_expected_artifact_key_when_absent():
    mapper = build_canonical_work_mapper(profiles())
    work = mapper(proposal(mission_principal_id="qwen"), attempt=1)
    assert work.metadata.get("mission_expected_artifact") is None


# ---------------------------------------------------------------------------
# expected-artifact hint from success criteria
# ---------------------------------------------------------------------------
def test_expected_artifact_from_criteria():
    assert build_expected_artifact_from_criteria(("Artifact WORK-PCP-002.md present.",)) == "WORK-PCP-002.md"
    assert build_expected_artifact_from_criteria(("Write report.json",)) == "report.json"
    assert build_expected_artifact_from_criteria(("mission_result.jsonl produced",)) == "mission_result.jsonl"


def test_expected_artifact_from_criteria_none():
    assert build_expected_artifact_from_criteria(("Backend returns a governed successful result.",)) is None
    assert build_expected_artifact_from_criteria(()) is None


# ---------------------------------------------------------------------------
# mission artifact verifier (ADR-0057, envelope reuse)
# ---------------------------------------------------------------------------
def test_mission_artifact_verify_ok(tmp_path: Path):
    (tmp_path / "WORK-PCP-002.md").write_text(envelope_text(), encoding="utf-8")
    verify = build_mission_artifact_verify("WORK-PCP-002.md")
    assert verify is not None
    assert verify(ready_work(tmp_path)) is True


def test_mission_artifact_verify_rejects_placeholder(tmp_path: Path):
    (tmp_path / "WORK-PCP-002.md").write_text("x", encoding="utf-8")
    verify = build_mission_artifact_verify("WORK-PCP-002.md")
    assert verify is not None
    assert verify(ready_work(tmp_path)) is False


def test_mission_artifact_verify_rejects_envelope_mismatch(tmp_path: Path):
    (tmp_path / "WORK-PCP-002.md").write_text(envelope_text(work_id="WORK-OTHER"), encoding="utf-8")
    verify = build_mission_artifact_verify("WORK-PCP-002.md")
    assert verify(ready_work(tmp_path)) is False


def test_mission_artifact_verify_rejects_missing_file(tmp_path: Path):
    verify = build_mission_artifact_verify("WORK-PCP-002.md")
    assert verify(ready_work(tmp_path)) is False


def test_mission_artifact_verify_none_when_no_expected():
    assert build_mission_artifact_verify(None) is None
    assert build_mission_artifact_verify("") is None
    assert build_mission_artifact_verify("  ") is None


# ---------------------------------------------------------------------------
# executor accepts artifact_verify param (backward compatible)
# ---------------------------------------------------------------------------
def test_executor_accepts_artifact_verify_param():
    verify = build_mission_artifact_verify("WORK-PCP-002.md")
    dispatcher = _StaticDispatcher()
    executor = ApcbMissionActionExecutor(
        dispatcher,
        None,
        profiles=profiles(),
        artifact_verify=verify,
    )
    assert executor.artifact_verify is verify


class _StaticDispatcher:
    def dispatch(self, work: WorkItemView) -> DispatchDecision:
        return DispatchDecision(
            work_id=work.work_id,
            mission_id=work.mission_id,
            principal_id=work.principal_id,
            attempt_number=work.attempt_number,
            dispatched=False,
            status="rejected",
            diagnostic=("no dispatch in this test",),
        )
