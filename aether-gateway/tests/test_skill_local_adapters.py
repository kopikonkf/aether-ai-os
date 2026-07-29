import asyncio
import json
from pathlib import Path

from aether.contracts import (
    EvolutionCheckKind, EvolutionCommand, SkillCandidate, SkillManifest, SkillProvenance,
    SkillRecord, SkillTriggerType, SkillUsageContract,
)
from aether_gateway.skills import LocalRuntimeSkillInstaller, LocalSkillBenchmarkSandbox


def candidate() -> SkillCandidate:
    return SkillCandidate(
        manifest=SkillManifest(
            name="math-helper",
            version="1.0.0",
            summary="Addition helper",
            instructions="Add two integers and return the exact result.",
            usage=SkillUsageContract(capabilities=("reason",)),
        ),
        provenance=SkillProvenance(
            trigger_type=SkillTriggerType.CAPABILITY_GAP,
            trigger_fingerprint="gap:math",
            evidence_ids=("evt-1",),
            observed_count=1,
            successful_count=0,
        ),
        deterministic_checks=(EvolutionCommand(("{python}", "-m", "pytest", "-q", "tests/test_skill.py"), EvolutionCheckKind.DETERMINISTIC, "unit"),),
        heldout_checks=(EvolutionCommand(("{python}", "-m", "pytest", "-q", "tests/test_skill_heldout.py"), EvolutionCheckKind.HELDOUT, "heldout"),),
        rationale="Close a measured capability gap.",
    )


def _workspace(root: Path) -> None:
    tests = root / "tests"
    tests.mkdir(parents=True)
    body = '''import json\nfrom pathlib import Path\n\ndef test_skill_manifest():\n    path = Path(".aether/skills/math-helper.json")\n    assert path.exists()\n    data = json.loads(path.read_text())\n    assert "Add two integers" in data["instructions"]\n'''
    (tests / "test_skill.py").write_text(body, encoding="utf-8")
    (tests / "test_skill_heldout.py").write_text(body.replace("test_skill_manifest", "test_skill_manifest_heldout"), encoding="utf-8")


def test_local_skill_sandbox_compares_baseline_and_candidate(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _workspace(workspace)
    sandbox = LocalSkillBenchmarkSandbox(workspace, tmp_path / "sandboxes")
    result = asyncio.run(sandbox.benchmark(candidate()))
    assert result.passed is True
    assert result.baseline_score == 0.0
    assert result.candidate_score == 1.0
    assert result.improvement == 1.0
    assert any(item.kind == EvolutionCheckKind.HELDOUT and item.phase == "candidate" for item in result.checks)


def test_runtime_installer_retains_artifact_on_archive_and_rollback(tmp_path: Path):
    installer = LocalRuntimeSkillInstaller(tmp_path / "registry")
    item = candidate()
    receipt = asyncio.run(installer.install(item))
    artifact = Path(receipt.install_path)
    pointer = Path(receipt.activation_pointer)
    assert artifact.exists()
    assert pointer.exists()
    record = SkillRecord(
        candidate_id=item.candidate_id,
        manifest=item.manifest,
        provenance=item.provenance,
        artifact_hash=item.artifact_hash,
        principal="founder",
        reason="Verified activation",
        install_receipt=receipt,
    )
    asyncio.run(installer.deactivate(record, reason="Explicit archive after review."))
    assert artifact.exists()
    assert json.loads(pointer.read_text())["status"] == "archived"
    asyncio.run(installer.rollback_install(receipt))
    assert artifact.exists()
    assert json.loads(pointer.read_text())["status"] == "rollback-no-active-skill"
