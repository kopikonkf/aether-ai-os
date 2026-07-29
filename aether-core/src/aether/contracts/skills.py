"""Runtime-neutral contracts for Aether-owned skills and their lifecycle."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable

from aether.contracts.evolution import EvolutionCheckResult, EvolutionCommand
from aether.utils.ids import new_id


class SkillTriggerType(StrEnum):
    REPEATED_SUCCESS = "repeated-success"
    CAPABILITY_GAP = "capability-gap"
    REVISION = "revision"


class SkillCandidateStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    REJECTED = "rejected"
    ACTIVE = "active"


class SkillLifecycleStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class SkillDecisionType(StrEnum):
    ACTIVATE = "activate"
    REJECT = "reject"


class SkillLifecycleAction(StrEnum):
    MARK_STALE = "mark-stale"
    ARCHIVE = "archive"
    REACTIVATE = "reactivate"
    SUPERSEDE = "supersede"


@dataclass(frozen=True)
class SkillUsageContract:
    capabilities: tuple[str, ...]
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)
    side_effects: tuple[str, ...] = field(default_factory=tuple)
    runtime_requirements: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SkillManifest:
    name: str
    version: str
    summary: str
    instructions: str
    usage: SkillUsageContract
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillProvenance:
    trigger_type: SkillTriggerType
    trigger_fingerprint: str
    evidence_ids: tuple[str, ...]
    observed_count: int
    successful_count: int
    source_workflow: str | None = None
    generator_id: str = "external"
    prior_skill_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        if self.observed_count <= 0:
            return 0.0
        return self.successful_count / self.observed_count


@dataclass(frozen=True)
class SkillCandidate:
    manifest: SkillManifest
    provenance: SkillProvenance
    deterministic_checks: tuple[EvolutionCommand, ...]
    heldout_checks: tuple[EvolutionCommand, ...]
    rationale: str
    retry_reason: str | None = None
    candidate_id: str = field(default_factory=lambda: new_id("skill-candidate"))
    created_at: str = ""
    status: SkillCandidateStatus = SkillCandidateStatus.DRAFT
    benchmark_id: str | None = None
    decision_id: str | None = None
    skill_id: str | None = None

    @property
    def artifact_hash(self) -> str:
        return skill_manifest_hash(self.manifest)


@dataclass(frozen=True)
class SkillBenchmark:
    candidate_id: str
    sandbox_id: str
    baseline_score: float
    candidate_score: float
    improvement: float
    regression_count: int
    checks: tuple[EvolutionCheckResult, ...]
    passed: bool
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    benchmark_id: str = field(default_factory=lambda: new_id("skill-benchmark"))
    created_at: str = ""


@dataclass(frozen=True)
class SkillDecision:
    candidate_id: str
    decision: SkillDecisionType
    principal: str
    channel: str
    reason: str
    decision_id: str = field(default_factory=lambda: new_id("skill-decision"))
    decided_at: str = ""
    skill_id: str | None = None


@dataclass(frozen=True)
class SkillInstallReceipt:
    adapter_id: str
    install_path: str
    activation_pointer: str
    previous_pointer_content: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillRecord:
    candidate_id: str
    manifest: SkillManifest
    provenance: SkillProvenance
    artifact_hash: str
    principal: str
    reason: str
    install_receipt: SkillInstallReceipt
    skill_id: str = field(default_factory=lambda: new_id("skill"))
    activated_at: str = ""
    lifecycle_status: SkillLifecycleStatus = SkillLifecycleStatus.ACTIVE


@dataclass(frozen=True)
class SkillUsageEvent:
    skill_id: str
    runtime_id: str
    success: bool
    duration_seconds: float
    session_id: str | None = None
    event_id: str | None = None
    error_fingerprint: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    usage_id: str = field(default_factory=lambda: new_id("skill-usage"))
    used_at: str = ""


@dataclass(frozen=True)
class SkillLifecycleEvent:
    skill_id: str
    action: SkillLifecycleAction
    principal: str
    channel: str
    reason: str
    lifecycle_id: str = field(default_factory=lambda: new_id("skill-lifecycle"))
    created_at: str = ""


@dataclass(frozen=True)
class SkillLifecycleReview:
    skill_id: str
    current_status: SkillLifecycleStatus
    recommended_status: SkillLifecycleStatus
    usage_count: int
    success_rate: float
    last_used_at: str | None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    reasons: tuple[str, ...] = field(default_factory=tuple)


def canonical_manifest_payload(manifest: SkillManifest) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "version": manifest.version,
        "summary": manifest.summary,
        "instructions": manifest.instructions,
        "usage": {
            "capabilities": list(manifest.usage.capabilities),
            "input_schema": dict(manifest.usage.input_schema),
            "output_schema": dict(manifest.usage.output_schema),
            "side_effects": list(manifest.usage.side_effects),
            "runtime_requirements": list(manifest.usage.runtime_requirements),
        },
        "tags": list(manifest.tags),
        "metadata": dict(manifest.metadata),
    }


def skill_manifest_hash(manifest: SkillManifest) -> str:
    raw = json.dumps(canonical_manifest_payload(manifest), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def skill_candidate_semantic_hash(candidate: SkillCandidate) -> str:
    payload = {
        "artifact_hash": candidate.artifact_hash,
        "trigger_type": candidate.provenance.trigger_type.value,
        "trigger_fingerprint": candidate.provenance.trigger_fingerprint,
        "prior_skill_id": candidate.provenance.prior_skill_id,
        "deterministic": [list(item.argv) for item in candidate.deterministic_checks],
        "heldout": [list(item.argv) for item in candidate.heldout_checks],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@runtime_checkable
class SkillBenchmarkSandbox(Protocol):
    async def benchmark(self, candidate: SkillCandidate, baseline: SkillRecord | None = None) -> SkillBenchmark: ...


@runtime_checkable
class SkillInstaller(Protocol):
    adapter_id: str

    async def install(self, candidate: SkillCandidate) -> SkillInstallReceipt: ...

    async def deactivate(self, record: SkillRecord, *, reason: str) -> None: ...

    async def rollback_install(self, receipt: SkillInstallReceipt) -> None: ...


@runtime_checkable
class SkillCandidateGenerator(Protocol):
    generator_id: str

    async def generate(self, context: Mapping[str, Any]) -> SkillCandidate: ...
