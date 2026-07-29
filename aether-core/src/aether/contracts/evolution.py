"""Provider-neutral contracts for Aether's internal evolution loop."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.utils.ids import new_id


class EvolutionTriggerType(StrEnum):
    FAILURE = "failure"
    CAPABILITY_GAP = "capability-gap"


class EvolutionTargetType(StrEnum):
    CODE = "code"
    SKILL = "skill"
    PROMPT = "prompt"
    WORKFLOW = "workflow"
    TOOL = "tool"


class EvolutionCandidateStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ROLLED_BACK = "rolled-back"


class EvolutionDecisionType(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"


class EvolutionCheckKind(StrEnum):
    DETERMINISTIC = "deterministic"
    HELDOUT = "heldout"


@dataclass(frozen=True)
class EvolutionTrigger:
    trigger_type: EvolutionTriggerType
    fingerprint: str
    summary: str
    evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    prior_learning_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    trigger_id: str = field(default_factory=lambda: new_id("evo-trigger"))
    created_at: str = ""


@dataclass(frozen=True)
class EvolutionCommand:
    argv: tuple[str, ...]
    kind: EvolutionCheckKind
    name: str
    timeout_seconds: int = 120


@dataclass(frozen=True)
class EvolutionCandidate:
    trigger_id: str
    trigger_fingerprint: str
    target_type: EvolutionTargetType
    target_path: str
    baseline_hash: str
    candidate_hash: str
    baseline_content: str
    candidate_content: str
    diff: str
    rationale: str
    generator_id: str
    deterministic_checks: tuple[EvolutionCommand, ...]
    heldout_checks: tuple[EvolutionCommand, ...]
    retry_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_id: str = field(default_factory=lambda: new_id("evo-candidate"))
    created_at: str = ""
    status: EvolutionCandidateStatus = EvolutionCandidateStatus.PROPOSED
    evaluation_id: str | None = None
    decision_id: str | None = None
    lineage_id: str | None = None


@dataclass(frozen=True)
class EvolutionCheckResult:
    name: str
    kind: EvolutionCheckKind
    phase: str
    passed: bool
    exit_code: int
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class EvolutionEvaluation:
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
    evaluation_id: str = field(default_factory=lambda: new_id("evo-eval"))
    created_at: str = ""


@dataclass(frozen=True)
class EvolutionDecision:
    candidate_id: str
    decision: EvolutionDecisionType
    principal: str
    channel: str
    reason: str
    decision_id: str = field(default_factory=lambda: new_id("evo-decision"))
    decided_at: str = ""
    lineage_id: str | None = None


@dataclass(frozen=True)
class EvolutionLineage:
    candidate_id: str
    target_path: str
    parent_hash: str
    promoted_hash: str
    backup_path: str
    principal: str
    reason: str
    lineage_id: str = field(default_factory=lambda: new_id("evo-lineage"))
    promoted_at: str = ""
    rolled_back_at: str | None = None
    rollback_principal: str | None = None
    rollback_reason: str | None = None


@dataclass(frozen=True)
class EvolutionLearning:
    fingerprint: str
    outcome: str
    summary: str
    candidate_id: str | None = None
    lineage_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    learning_id: str = field(default_factory=lambda: new_id("evo-learning"))
    created_at: str = ""


@dataclass(frozen=True)
class PromotionReceipt:
    target_path: str
    parent_hash: str
    promoted_hash: str
    backup_path: str


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def candidate_semantic_hash(candidate: EvolutionCandidate) -> str:
    payload = {
        "trigger_fingerprint": candidate.trigger_fingerprint,
        "target_type": candidate.target_type.value,
        "target_path": candidate.target_path,
        "baseline_hash": candidate.baseline_hash,
        "candidate_hash": candidate.candidate_hash,
        "checks": [list(item.argv) for item in (*candidate.deterministic_checks, *candidate.heldout_checks)],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@runtime_checkable
class EvolutionSandbox(Protocol):
    async def evaluate(self, candidate: EvolutionCandidate) -> EvolutionEvaluation: ...


@runtime_checkable
class EvolutionPromoter(Protocol):
    async def promote(self, candidate: EvolutionCandidate) -> PromotionReceipt: ...

    async def rollback(self, lineage: EvolutionLineage) -> None: ...


@runtime_checkable
class EvolutionCandidateGenerator(Protocol):
    generator_id: str

    async def generate(self, trigger: EvolutionTrigger, context: Mapping[str, Any]) -> EvolutionCandidate: ...
