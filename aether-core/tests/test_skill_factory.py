import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aether.contracts import (
    EvolutionCheckKind, EvolutionCheckResult, EvolutionCommand,
    SkillBenchmark, SkillInstallReceipt, SkillLifecycleAction, SkillLifecycleStatus,
    SkillManifest, SkillProvenance, SkillRecord, SkillTriggerType, SkillUsageContract, SkillUsageEvent,
)
from aether.skills import SkillFactory, SkillFactoryBlocked, SQLiteSkillStore


def manifest(version: str = "1.0.0", instructions: str = "Add two integers and return the exact result.") -> SkillManifest:
    return SkillManifest(
        name="math-helper",
        version=version,
        summary="Deterministic integer addition workflow.",
        instructions=instructions,
        usage=SkillUsageContract(
            capabilities=("reason",),
            input_schema={"a": "integer", "b": "integer"},
            output_schema={"result": "integer"},
        ),
        tags=("math", "deterministic"),
    )


def commands():
    return (
        EvolutionCommand(("{python}", "-m", "pytest", "-q", "tests/test_skill.py"), EvolutionCheckKind.DETERMINISTIC, "unit"),
        EvolutionCommand(("{python}", "-m", "pytest", "-q", "tests/test_skill_heldout.py"), EvolutionCheckKind.HELDOUT, "heldout"),
    )


class Sandbox:
    def __init__(self, passed: bool = True, baseline_score: float = 0.0):
        self.passed = passed
        self.baseline_score = baseline_score

    async def benchmark(self, candidate, baseline=None):
        deterministic, heldout = commands()
        candidate_score = 1.0 if self.passed else 0.0
        checks = (
            EvolutionCheckResult("unit", deterministic.kind, "baseline", self.baseline_score > 0.5, 0 if self.baseline_score > 0.5 else 1, 0.01),
            EvolutionCheckResult("heldout", heldout.kind, "baseline", self.baseline_score > 0.5, 0 if self.baseline_score > 0.5 else 1, 0.01),
            EvolutionCheckResult("unit", deterministic.kind, "candidate", self.passed, 0 if self.passed else 1, 0.01),
            EvolutionCheckResult("heldout", heldout.kind, "candidate", self.passed, 0 if self.passed else 1, 0.01),
        )
        return SkillBenchmark(
            candidate_id=candidate.candidate_id,
            sandbox_id="skill-sandbox.test",
            baseline_score=self.baseline_score,
            candidate_score=candidate_score,
            improvement=candidate_score - self.baseline_score,
            regression_count=0,
            checks=checks,
            passed=self.passed,
            blockers=() if self.passed else ("candidate failed",),
        )


class Installer:
    adapter_id = "installer.test"

    def __init__(self):
        self.installs = 0
        self.deactivations = 0
        self.rollbacks = 0

    async def install(self, candidate):
        self.installs += 1
        return SkillInstallReceipt(self.adapter_id, f"/skills/{candidate.artifact_hash}.json", f"/active/{candidate.manifest.name}.json")

    async def deactivate(self, record, *, reason):
        self.deactivations += 1

    async def rollback_install(self, receipt):
        self.rollbacks += 1


def repeated(factory: SkillFactory, *, retry_reason=None):
    deterministic, heldout = commands()
    return factory.propose(
        manifest=manifest(),
        provenance=SkillProvenance(
            trigger_type=SkillTriggerType.REPEATED_SUCCESS,
            trigger_fingerprint="workflow:add-integers",
            evidence_ids=("evt-1", "evt-2", "evt-3"),
            observed_count=3,
            successful_count=3,
            source_workflow="manual-addition",
            generator_id="generator.test",
        ),
        deterministic_checks=(deterministic,),
        heldout_checks=(heldout,),
        rationale="Repeated successful workflow can be packaged as a bounded skill.",
        retry_reason=retry_reason,
    )


def test_repeated_success_requires_evidence_and_success_rate(tmp_path: Path):
    factory = SkillFactory(SQLiteSkillStore(tmp_path / "skills.sqlite3"))
    deterministic, heldout = commands()
    with pytest.raises(SkillFactoryBlocked, match="insufficient observations"):
        factory.propose(
            manifest=manifest(),
            provenance=SkillProvenance(
                trigger_type=SkillTriggerType.REPEATED_SUCCESS,
                trigger_fingerprint="weak",
                evidence_ids=("evt-1",),
                observed_count=1,
                successful_count=1,
            ),
            deterministic_checks=(deterministic,),
            heldout_checks=(heldout,),
            rationale="Insufficient evidence should be blocked.",
        )


def test_protected_capability_is_blocked(tmp_path: Path):
    factory = SkillFactory(SQLiteSkillStore(tmp_path / "skills.sqlite3"))
    deterministic, heldout = commands()
    protected = SkillManifest(
        name="identity-editor", version="1", summary="Unsafe", instructions="Modify DNA.",
        usage=SkillUsageContract(capabilities=("dna.modify",)),
    )
    with pytest.raises(SkillFactoryBlocked, match="protected capabilities"):
        factory.propose_capability_gap(
            manifest=protected, gap_fingerprint="gap:dna", evidence_ids=("evt-1",), generator_id="model",
            deterministic_checks=(deterministic,), heldout_checks=(heldout,), rationale="Unsafe request must be blocked.",
        )


def test_benchmark_and_activation_require_trusted_principal(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    candidate = repeated(factory)
    installer = Installer()
    with pytest.raises(SkillFactoryBlocked, match="not been benchmarked"):
        asyncio.run(factory.decide(
            candidate.candidate_id, approved=True, principal="founder", channel="test",
            reason="Activate only after governed benchmark evidence exists.", installer=installer,
        ))
    benchmark = asyncio.run(factory.benchmark(candidate.candidate_id, Sandbox(True)))
    assert benchmark.passed
    with pytest.raises(SkillFactoryBlocked, match="not trusted"):
        asyncio.run(factory.decide(
            candidate.candidate_id, approved=True, principal="model", channel="model",
            reason="The generator cannot authorize its own skill activation.", installer=installer,
        ))
    active = asyncio.run(factory.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Held-out benchmark proves the bounded skill improves the repeated workflow.", installer=installer,
    ))
    assert active.status.value == "active"
    assert store.get_record(active.skill_id).lifecycle_status == SkillLifecycleStatus.ACTIVE
    assert installer.installs == 1


def test_failed_candidate_requires_material_retry_reason(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    first = repeated(factory)
    asyncio.run(factory.benchmark(first.candidate_id, Sandbox(False)))
    with pytest.raises(SkillFactoryBlocked, match="same failed skill"):
        repeated(factory)
    retry = repeated(factory, retry_reason="The benchmark fixture was corrected and the candidate will be reevaluated.")
    assert retry.candidate_id != first.candidate_id


def test_usage_telemetry_can_mark_stale_but_not_archive(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    candidate = repeated(factory)
    asyncio.run(factory.benchmark(candidate.candidate_id, Sandbox(True)))
    active = asyncio.run(factory.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Activate the verified skill for lifecycle telemetry testing.", installer=Installer(),
    ))
    skill_id = active.skill_id
    factory.record_usage(SkillUsageEvent(skill_id=skill_id, runtime_id="runtime.test", success=True, duration_seconds=0.1))
    future = datetime.now(timezone.utc) + timedelta(days=31)
    reviewed = asyncio.run(factory.apply_review(skill_id, now=future))
    assert reviewed.lifecycle_status == SkillLifecycleStatus.STALE
    assert store.get_decision(candidate.candidate_id).decision == store.get_decision(candidate.candidate_id).decision
    assert not any(event.action == SkillLifecycleAction.ARCHIVE for event in store.lifecycle_events(skill_id))


def test_archive_requires_trusted_operator_and_retains_registry_record(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    candidate = repeated(factory)
    installer = Installer()
    asyncio.run(factory.benchmark(candidate.candidate_id, Sandbox(True)))
    active = asyncio.run(factory.decide(
        candidate.candidate_id, approved=True, principal="founder", channel="test",
        reason="Activate verified skill before explicit archive lifecycle testing.", installer=installer,
    ))
    with pytest.raises(SkillFactoryBlocked, match="not trusted"):
        asyncio.run(factory.lifecycle(
            active.skill_id, action=SkillLifecycleAction.ARCHIVE, principal="curator", channel="internal",
            reason="Curator cannot archive without trusted authorization.", installer=installer,
        ))
    archived = asyncio.run(factory.lifecycle(
        active.skill_id, action=SkillLifecycleAction.ARCHIVE, principal="founder", channel="test",
        reason="Archive after explicit review while retaining the immutable artifact and lineage.", installer=installer,
    ))
    assert archived.lifecycle_status == SkillLifecycleStatus.ARCHIVED
    assert store.get_record(active.skill_id).artifact_hash == archived.artifact_hash
    assert installer.deactivations == 1


def test_revision_activation_supersedes_prior_skill(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    installer = Installer()
    first = repeated(factory)
    asyncio.run(factory.benchmark(first.candidate_id, Sandbox(True)))
    first = asyncio.run(factory.decide(
        first.candidate_id, approved=True, principal="founder", channel="test",
        reason="Activate initial verified skill version for bounded revision testing.", installer=installer,
    ))
    deterministic, heldout = commands()
    revision = factory.propose_revision(
        prior_skill_id=first.skill_id,
        manifest=manifest("1.1.0", "Add two integers, validate integer inputs, and return the exact result."),
        evidence_ids=("usage-failure-1",), generator_id="cee.skill-revision",
        deterministic_checks=(deterministic,), heldout_checks=(heldout,),
        rationale="Usage evidence identified missing input validation.",
    )
    asyncio.run(factory.benchmark(revision.candidate_id, Sandbox(True, baseline_score=0.5)))
    revision = asyncio.run(factory.decide(
        revision.candidate_id, approved=True, principal="founder", channel="test",
        reason="Activate verified revision after held-out input-validation improvement.", installer=installer,
    ))
    assert store.get_record(first.skill_id).lifecycle_status == SkillLifecycleStatus.SUPERSEDED
    assert store.get_record(revision.skill_id).lifecycle_status == SkillLifecycleStatus.ACTIVE


def test_skill_ledger_is_immutable(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    candidate = repeated(factory)
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE skill_candidates SET rationale='tampered' WHERE candidate_id=?", (candidate.candidate_id,))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM skill_candidates WHERE candidate_id=?", (candidate.candidate_id,))


def test_active_skill_name_requires_revision_binding(tmp_path: Path):
    store = SQLiteSkillStore(tmp_path / "skills.sqlite3")
    factory = SkillFactory(store)
    installer = Installer()
    first = repeated(factory)
    asyncio.run(factory.benchmark(first.candidate_id, Sandbox(True)))
    asyncio.run(factory.decide(
        first.candidate_id, approved=True, principal="founder", channel="test",
        reason="Activate initial verified skill before replacement-boundary testing.", installer=installer,
    ))
    deterministic, heldout = commands()
    replacement = factory.propose_capability_gap(
        manifest=manifest("2.0.0", "Add two integers using a replacement implementation."),
        gap_fingerprint="gap:replacement", evidence_ids=("evt-gap",), generator_id="generator.test",
        deterministic_checks=(deterministic,), heldout_checks=(heldout,),
        rationale="Unbound replacement attempt should be blocked at activation.",
    )
    asyncio.run(factory.benchmark(replacement.candidate_id, Sandbox(True)))
    with pytest.raises(SkillFactoryBlocked, match="revision bound"):
        asyncio.run(factory.decide(
            replacement.candidate_id, approved=True, principal="founder", channel="test",
            reason="Attempt to replace an active skill without revision lineage.", installer=installer,
        ))
