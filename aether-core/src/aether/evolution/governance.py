"""Constitutional guardrails for the internal evolution loop."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Any

import yaml

from aether.contracts.evolution import EvolutionCandidate, EvolutionEvaluation


@dataclass(frozen=True)
class EvolutionPolicy:
    protected_paths: tuple[str, ...]
    protected_names: tuple[str, ...]
    allowed_target_types: tuple[str, ...]
    max_candidate_bytes: int
    max_growth_ratio: float
    max_commands_per_phase: int
    max_command_timeout_seconds: int
    minimum_improvement: float
    maximum_regressions: int
    trusted_principals: tuple[str, ...]

    @classmethod
    def load(cls) -> "EvolutionPolicy":
        path = files("aether.evolution").joinpath("internal_evolution.yaml")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        constraints = data["constraints"]
        return cls(
            protected_paths=tuple(data["protected_paths"]),
            protected_names=tuple(data["protected_names"]),
            allowed_target_types=tuple(data["allowed_target_types"]),
            max_candidate_bytes=int(constraints["max_candidate_bytes"]),
            max_growth_ratio=float(constraints["max_growth_ratio"]),
            max_commands_per_phase=int(constraints["max_commands_per_phase"]),
            max_command_timeout_seconds=int(constraints["max_command_timeout_seconds"]),
            minimum_improvement=float(constraints["minimum_improvement"]),
            maximum_regressions=int(constraints["maximum_regressions"]),
            trusted_principals=tuple(data["trusted_principals"]),
        )


class EvolutionBlocked(RuntimeError):
    def __init__(self, blockers: tuple[str, ...]):
        self.blockers = blockers
        super().__init__("evolution blocked: " + "; ".join(blockers))


class InternalEvolutionGovernor:
    def __init__(self, policy: EvolutionPolicy | None = None) -> None:
        self.policy = policy or EvolutionPolicy.load()

    def validate_candidate(self, candidate: EvolutionCandidate) -> tuple[str, ...]:
        blockers: list[str] = []
        path = PurePosixPath(candidate.target_path.replace("\\", "/"))
        normalized = str(path)
        if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
            blockers.append("target path must be a safe relative path")
        if path.name in self.policy.protected_names:
            blockers.append(f"protected artifact cannot evolve: {path.name}")
        for protected in self.policy.protected_paths:
            protected_path = PurePosixPath(protected)
            if path == protected_path or protected_path in path.parents:
                blockers.append(f"protected path cannot evolve: {protected}")
        if candidate.target_type.value not in self.policy.allowed_target_types:
            blockers.append(f"target type is not allowed: {candidate.target_type.value}")
        candidate_bytes = len(candidate.candidate_content.encode("utf-8"))
        if candidate_bytes > self.policy.max_candidate_bytes:
            blockers.append(f"candidate exceeds maximum size: {candidate_bytes}")
        baseline_size = max(1, len(candidate.baseline_content.encode("utf-8")))
        growth = (candidate_bytes - baseline_size) / baseline_size
        if growth > self.policy.max_growth_ratio:
            blockers.append(f"candidate growth exceeds limit: {growth:.1%}")
        if not candidate.deterministic_checks:
            blockers.append("deterministic checks are required")
        if not candidate.heldout_checks:
            blockers.append("held-out checks are required")
        if len(candidate.deterministic_checks) > self.policy.max_commands_per_phase:
            blockers.append("too many deterministic commands")
        if len(candidate.heldout_checks) > self.policy.max_commands_per_phase:
            blockers.append("too many held-out commands")
        for command in (*candidate.deterministic_checks, *candidate.heldout_checks):
            if command.timeout_seconds > self.policy.max_command_timeout_seconds:
                blockers.append(f"command timeout exceeds policy: {command.name}")
        if candidate.baseline_hash == candidate.candidate_hash:
            blockers.append("candidate does not change the baseline")
        return tuple(dict.fromkeys(blockers))

    def validate_evaluation(self, evaluation: EvolutionEvaluation) -> tuple[str, ...]:
        blockers = list(evaluation.blockers)
        if not evaluation.passed:
            blockers.append("evaluation did not pass")
        if evaluation.improvement < self.policy.minimum_improvement:
            blockers.append(
                f"improvement {evaluation.improvement:.3f} is below minimum {self.policy.minimum_improvement:.3f}"
            )
        if evaluation.regression_count > self.policy.maximum_regressions:
            blockers.append(f"regressions exceed policy: {evaluation.regression_count}")
        if not any(item.kind.value == "heldout" and item.phase == "candidate" for item in evaluation.checks):
            blockers.append("held-out candidate results are missing")
        return tuple(dict.fromkeys(blockers))

    def validate_decision(self, *, principal: str, reason: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if principal not in self.policy.trusted_principals:
            blockers.append(f"principal is not trusted for evolution promotion: {principal}")
        if len(reason.strip()) < 12:
            blockers.append("decision reason must be explicit")
        return tuple(blockers)
