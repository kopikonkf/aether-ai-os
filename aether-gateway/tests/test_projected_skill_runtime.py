import asyncio
from pathlib import Path

from aether.contracts import (
    EvolutionCheckKind, EvolutionCommand, RuntimeCommand, SkillCandidate, SkillInstallReceipt,
    SkillLifecycleAction, SkillLifecycleEvent, SkillManifest, SkillProvenance, SkillRecord,
    SkillTriggerType, SkillUsageContract, skill_candidate_semantic_hash,
)
from aether.skills import SkillFactory, SQLiteSkillStore
from aether_gateway.skills import LocalProjectedSkillRuntimeAdapter


def add_active(store: SQLiteSkillStore):
    cmd = EvolutionCommand(("{python}", "-m", "compileall", "."), EvolutionCheckKind.DETERMINISTIC, "compile")
    candidate = SkillCandidate(
        manifest=SkillManifest(
            name="greeting-skill",
            version="1.0.0",
            summary="Render a deterministic greeting.",
            instructions="Use the bounded template runtime.",
            usage=SkillUsageContract(
                capabilities=("greet",),
                input_schema={"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
                output_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
                runtime_requirements=("aether.template-v1",),
            ),
            metadata={"execution": {"kind": "template-v1", "template": "Hello, {name}!"}},
        ),
        provenance=SkillProvenance(SkillTriggerType.CAPABILITY_GAP, "gap:greet", ("evt-1",), 1, 0),
        deterministic_checks=(cmd,),
        heldout_checks=(cmd,),
        rationale="Test deterministic runtime projection.",
    )
    store.add_candidate(candidate, skill_candidate_semantic_hash(candidate))
    return store.add_record(SkillRecord(
        candidate_id=candidate.candidate_id,
        manifest=candidate.manifest,
        provenance=candidate.provenance,
        artifact_hash=candidate.artifact_hash,
        principal="founder",
        reason="Activated for local projected runtime testing.",
        install_receipt=SkillInstallReceipt("installer.test", "/tmp/a", "/tmp/p"),
    ))


def command(record, **changes):
    args = {
        "skill_id": record.skill_id,
        "artifact_hash": record.artifact_hash,
        "capability": "greet",
        "input": {"name": "Aether"},
        "requirement_id": "cap-1",
    }
    args.update(changes)
    return RuntimeCommand("skill.execute", args, capability="skill.execute", correlation_id="corr-1")


def test_runtime_projects_executes_verifies_and_records_usage(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    record = add_active(store)
    runtime = LocalProjectedSkillRuntimeAdapter(store, factory, tmp_path / "projections")
    result = asyncio.run(runtime.execute(command(record)))
    assert result.ok is True
    assert result.output == {"text": "Hello, Aether!"}
    assert Path(result.metadata["projection_path"]).exists()
    assert result.metadata["result_verified"] is True
    assert len(store.usages(record.skill_id)) == 1
    assert store.usages(record.skill_id)[0].success is True


def test_runtime_rejects_hash_mismatch_and_archived_skill(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    record = add_active(store)
    runtime = LocalProjectedSkillRuntimeAdapter(store, factory, tmp_path / "projections")
    mismatch = asyncio.run(runtime.execute(command(record, artifact_hash="tampered")))
    assert mismatch.ok is False
    assert "hash" in mismatch.error
    store.add_lifecycle(SkillLifecycleEvent(record.skill_id, SkillLifecycleAction.ARCHIVE, "founder", "test", "Archive for runtime test."))
    archived = asyncio.run(runtime.execute(command(record)))
    assert archived.ok is False
    assert "not active" in archived.error


def test_runtime_input_failure_is_telemetry(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    record = add_active(store)
    runtime = LocalProjectedSkillRuntimeAdapter(store, factory, tmp_path / "projections")
    result = asyncio.run(runtime.execute(command(record, input={})))
    assert result.ok is False
    usages = store.usages(record.skill_id)
    assert usages[0].success is False
    assert usages[0].error_fingerprint
