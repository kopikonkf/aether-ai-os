from __future__ import annotations

import json
import shutil
from pathlib import Path

from aether.contracts.actions import (
    ActionApproval,
    ActionProposal,
    ActionRisk,
    ActionScope,
    ActionTarget,
    canonical_action_hash,
)
from aether.dna.loader import DNALoader
from aether.governance.actions import ActionGovernor
from aether.governance.north_star_authority import NorthStarAuthority
from aether.governance.proposal import Proposal


def _source_dna_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "aether" / "dna"


def _copied_dna_dir(tmp_path: Path) -> Path:
    target = tmp_path / "dna"
    shutil.copytree(_source_dna_dir(), target)
    return target


def test_default_dna_matches_founder_reviewed_manifest() -> None:
    report = DNALoader().integrity_report()
    assert report["ok"] is True
    assert report["errors"] == []
    assert set(report["files"]) == {
        "north_star.yaml",
        "Genome.md",
        "aether.core.json",
    }
    assert all(item["matches"] for item in report["files"].values())


def test_dna_integrity_detects_tampered_genome(tmp_path: Path) -> None:
    dna_dir = _copied_dna_dir(tmp_path)
    genome = dna_dir / "Genome.md"
    genome.write_text(genome.read_text(encoding="utf-8") + "\nunauthorized change\n", encoding="utf-8")

    report = DNALoader(dna_dir).integrity_report()

    assert report["ok"] is False
    assert report["files"]["Genome.md"]["matches"] is False
    assert "Genome.md: sha256-mismatch" in report["errors"]


def test_dna_integrity_rejects_incomplete_manifest(tmp_path: Path) -> None:
    dna_dir = _copied_dna_dir(tmp_path)
    manifest_path = dna_dir / DNALoader.MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["files"]["aether.core.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = DNALoader(dna_dir).integrity_report()

    assert report["ok"] is False
    assert any("manifest missing canonical files" in item for item in report["errors"])


def test_irreversible_proposal_without_approval_path_is_hard_vetoed() -> None:
    result = NorthStarAuthority().evaluate(Proposal(
        action="wipe production state",
        reason="Replace all current production state",
        metadata={"irreversible": True},
    ))

    assert result.approved is False
    assert result.alignment_score == 0.0
    assert "irreversible action" in (result.veto_reason or "")


def test_review_bypass_is_hard_vetoed_even_with_high_confidence() -> None:
    result = NorthStarAuthority().evaluate(Proposal(
        action="force_deploy",
        reason="skip_review to save time",
        confidence=1.0,
        metadata={"dee_approved": True},
    ))

    assert result.approved is False
    assert result.alignment_score == 0.0
    assert "review bypass" in (result.veto_reason or "")


def test_north_star_amendment_requires_both_founder_approval_and_protocol_marker() -> None:
    authority = NorthStarAuthority()

    denied = authority.evaluate(Proposal(
        action="change_north_star",
        reason="Replace the current direction",
        metadata={"dee_approved": True},
    ))
    allowed_candidate = authority.evaluate(Proposal(
        action="change_north_star",
        reason="Founder-authorized amendment candidate for reviewed source change",
        metadata={
            "dee_approved": True,
            "constitutional_amendment": True,
        },
    ))

    assert denied.approved is False
    assert allowed_candidate.approved is True
    assert any("amendment candidate" in item for item in allowed_candidate.warnings)


def test_action_governor_preserves_exact_founder_approval_flow_for_irreversible_work() -> None:
    governor = ActionGovernor()
    proposal = ActionProposal(
        ActionTarget.TOOL,
        "write",
        {"path": "workspace/governed.txt", "content": "bounded"},
        (ActionScope.WRITE,),
        "Write one bounded governed artifact",
        ActionRisk.MEDIUM,
        False,
    )

    pending = governor.review(proposal)
    approval = ActionApproval(
        "founder",
        (ActionScope.WRITE,),
        "Founder approved the exact bounded action",
        action_hash=canonical_action_hash(proposal),
    )
    approved = governor.review(proposal, approval)

    assert pending.approved is False
    assert pending.mode == "approval-required"
    assert approved.approved is True
    assert approved.mode == "human-approved"
