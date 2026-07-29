"""Governance policy for Aether's skill factory and curator lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
import json
from importlib.resources import files
from typing import Any

import yaml

from aether.contracts.skills import (
    SkillBenchmark,
    SkillCandidate,
    canonical_manifest_payload,
    SkillLifecycleAction,
    SkillLifecycleStatus,
    SkillRecord,
    SkillTriggerType,
)


@dataclass(frozen=True)
class SkillFactoryPolicy:
    maximum_artifact_bytes: int
    maximum_commands_per_phase: int
    maximum_command_timeout_seconds: int
    allowed_trigger_types: tuple[str, ...]
    repeated_minimum_observations: int
    repeated_minimum_success_rate: float
    repeated_minimum_evidence_records: int
    capability_gap_minimum_evidence_records: int
    revision_minimum_evidence_records: int
    minimum_candidate_score: float
    minimum_improvement: float
    maximum_regressions: int
    heldout_required: bool
    stale_after_days_without_usage: int
    minimum_usage_for_failure_review: int
    maximum_failure_rate: float
    archive_requires_trusted_principal: bool
    reactivation_requires_benchmark: bool
    trusted_principals: tuple[str, ...]
    protected_capabilities: tuple[str, ...]

    @classmethod
    def load(cls) -> "SkillFactoryPolicy":
        path = files("aether.skills").joinpath("skill_factory.yaml")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        constraints = data["candidate_constraints"]
        repeated = constraints["repeated_success"]
        benchmark = data["benchmark"]
        lifecycle = data["lifecycle"]
        return cls(
            maximum_artifact_bytes=int(constraints["maximum_artifact_bytes"]),
            maximum_commands_per_phase=int(constraints["maximum_commands_per_phase"]),
            maximum_command_timeout_seconds=int(constraints["maximum_command_timeout_seconds"]),
            allowed_trigger_types=tuple(constraints["allowed_trigger_types"]),
            repeated_minimum_observations=int(repeated["minimum_observations"]),
            repeated_minimum_success_rate=float(repeated["minimum_success_rate"]),
            repeated_minimum_evidence_records=int(repeated["minimum_evidence_records"]),
            capability_gap_minimum_evidence_records=int(constraints["capability_gap"]["minimum_evidence_records"]),
            revision_minimum_evidence_records=int(constraints["revision"]["minimum_evidence_records"]),
            minimum_candidate_score=float(benchmark["minimum_candidate_score"]),
            minimum_improvement=float(benchmark["minimum_improvement"]),
            maximum_regressions=int(benchmark["maximum_regressions"]),
            heldout_required=bool(benchmark["heldout_required"]),
            stale_after_days_without_usage=int(lifecycle["stale_after_days_without_usage"]),
            minimum_usage_for_failure_review=int(lifecycle["minimum_usage_for_failure_review"]),
            maximum_failure_rate=float(lifecycle["maximum_failure_rate"]),
            archive_requires_trusted_principal=bool(lifecycle["archive_requires_trusted_principal"]),
            reactivation_requires_benchmark=bool(lifecycle["reactivation_requires_benchmark"]),
            trusted_principals=tuple(data["trusted_principals"]),
            protected_capabilities=tuple(data["protected_capabilities"]),
        )


class SkillFactoryBlocked(RuntimeError):
    def __init__(self, blockers: tuple[str, ...]):
        self.blockers = blockers
        super().__init__("skill factory blocked: " + "; ".join(blockers))


class SkillFactoryGovernor:
    def __init__(self, policy: SkillFactoryPolicy | None = None) -> None:
        self.policy = policy or SkillFactoryPolicy.load()

    def validate_candidate(self, candidate: SkillCandidate, baseline: SkillRecord | None = None) -> tuple[str, ...]:
        blockers: list[str] = []
        manifest = candidate.manifest
        provenance = candidate.provenance
        if provenance.trigger_type.value not in self.policy.allowed_trigger_types:
            blockers.append(f"unsupported skill trigger: {provenance.trigger_type.value}")
        if not manifest.name.strip() or any(char in manifest.name for char in "/\\"):
            blockers.append("skill name must be non-empty and path-neutral")
        if not manifest.version.strip():
            blockers.append("skill version is required")
        if not manifest.summary.strip() or not manifest.instructions.strip():
            blockers.append("skill summary and instructions are required")
        artifact_size = len(json.dumps(canonical_manifest_payload(manifest), ensure_ascii=False, sort_keys=True).encode("utf-8"))
        if artifact_size > self.policy.maximum_artifact_bytes:
            blockers.append(f"skill artifact exceeds maximum size: {artifact_size}")
        if not manifest.usage.capabilities:
            blockers.append("at least one capability is required")
        protected = set(manifest.usage.capabilities) & set(self.policy.protected_capabilities)
        if protected:
            blockers.append("skill requests constitutionally protected capabilities: " + ", ".join(sorted(protected)))
        if not candidate.deterministic_checks:
            blockers.append("deterministic benchmark commands are required")
        if not candidate.heldout_checks:
            blockers.append("held-out benchmark commands are required")
        if len(candidate.deterministic_checks) > self.policy.maximum_commands_per_phase:
            blockers.append("too many deterministic benchmark commands")
        if len(candidate.heldout_checks) > self.policy.maximum_commands_per_phase:
            blockers.append("too many held-out benchmark commands")
        for command in (*candidate.deterministic_checks, *candidate.heldout_checks):
            if command.timeout_seconds > self.policy.maximum_command_timeout_seconds:
                blockers.append(f"benchmark timeout exceeds policy: {command.name}")
        evidence_count = len(set(provenance.evidence_ids))
        if provenance.trigger_type == SkillTriggerType.REPEATED_SUCCESS:
            if provenance.observed_count < self.policy.repeated_minimum_observations:
                blockers.append("repeated workflow has insufficient observations")
            if provenance.success_rate < self.policy.repeated_minimum_success_rate:
                blockers.append("repeated workflow success rate is below policy")
            if evidence_count < self.policy.repeated_minimum_evidence_records:
                blockers.append("repeated workflow has insufficient evidence records")
        elif provenance.trigger_type == SkillTriggerType.CAPABILITY_GAP:
            if evidence_count < self.policy.capability_gap_minimum_evidence_records:
                blockers.append("capability gap requires evidence")
        elif provenance.trigger_type == SkillTriggerType.REVISION:
            if evidence_count < self.policy.revision_minimum_evidence_records:
                blockers.append("skill revision requires evidence")
            if not provenance.prior_skill_id:
                blockers.append("skill revision requires prior_skill_id")
            if baseline is None:
                blockers.append("skill revision baseline was not found")
            elif baseline.artifact_hash == candidate.artifact_hash:
                blockers.append("skill revision does not change the active artifact")
        if baseline is not None and baseline.manifest.name != manifest.name:
            blockers.append("revision must preserve the skill name")
        return tuple(dict.fromkeys(blockers))

    def validate_benchmark(self, benchmark: SkillBenchmark) -> tuple[str, ...]:
        blockers = list(benchmark.blockers)
        if not benchmark.passed:
            blockers.append("benchmark did not pass")
        if benchmark.candidate_score < self.policy.minimum_candidate_score:
            blockers.append(
                f"candidate score {benchmark.candidate_score:.3f} is below minimum {self.policy.minimum_candidate_score:.3f}"
            )
        if benchmark.improvement < self.policy.minimum_improvement:
            blockers.append(
                f"improvement {benchmark.improvement:.3f} is below minimum {self.policy.minimum_improvement:.3f}"
            )
        if benchmark.regression_count > self.policy.maximum_regressions:
            blockers.append(f"regressions exceed policy: {benchmark.regression_count}")
        if self.policy.heldout_required and not any(
            item.kind.value == "heldout" and item.phase == "candidate" for item in benchmark.checks
        ):
            blockers.append("held-out candidate benchmark is missing")
        return tuple(dict.fromkeys(blockers))

    def validate_activation(self, *, principal: str, reason: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if principal not in self.policy.trusted_principals:
            blockers.append(f"principal is not trusted for skill activation: {principal}")
        if len(reason.strip()) < 12:
            blockers.append("activation reason must be explicit")
        return tuple(blockers)

    def validate_lifecycle(
        self,
        action: SkillLifecycleAction,
        *,
        principal: str,
        reason: str,
        record: SkillRecord,
        benchmark_passed: bool = False,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(reason.strip()) < 12:
            blockers.append("lifecycle reason must be explicit")
        if action in {SkillLifecycleAction.ARCHIVE, SkillLifecycleAction.REACTIVATE}:
            if principal not in self.policy.trusted_principals:
                blockers.append(f"principal is not trusted for skill lifecycle action: {principal}")
        if action == SkillLifecycleAction.REACTIVATE:
            if record.lifecycle_status != SkillLifecycleStatus.ARCHIVED:
                blockers.append("only archived skills may be reactivated")
            if self.policy.reactivation_requires_benchmark and not benchmark_passed:
                blockers.append("reactivation requires a fresh passing benchmark")
        if action == SkillLifecycleAction.ARCHIVE and record.lifecycle_status == SkillLifecycleStatus.SUPERSEDED:
            blockers.append("superseded skill already has a terminal inactive lifecycle")
        return tuple(dict.fromkeys(blockers))
