"""Provider- and runtime-neutral contracts for capability routing and skill execution."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.contracts.actions import ActionRisk, ActionScope
from aether.contracts.skills import SkillRecord, SkillUsageEvent
from aether.utils.ids import new_id


class CapabilityRouteStatus(StrEnum):
    SELECTED = "selected"
    PENDING_APPROVAL = "pending-approval"
    COMPLETED = "completed"
    FALLBACK_COMPLETED = "fallback-completed"
    BLOCKED = "blocked"
    NOT_FOUND = "not-found"
    FAILED = "failed"


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    required_runtime_features: tuple[str, ...] = field(default_factory=tuple)
    allowed_side_effects: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    risk: ActionRisk = ActionRisk.LOW
    reversible: bool = True
    allow_fallback: bool = True
    session_id: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    requirement_id: str = field(default_factory=lambda: new_id("capability"))


@dataclass(frozen=True)
class RuntimeSkillProfile:
    """Opaque runtime compatibility profile supplied by an adapter.

    ``routing_key`` is an internal dispatch token. Core treats it as opaque and
    never branches on a runtime product name.
    """

    routing_key: str
    adapter_id: str
    operations: tuple[str, ...] = ("skill.execute",)
    runtime_features: tuple[str, ...] = field(default_factory=tuple)
    supported_side_effects: tuple[str, ...] = field(default_factory=tuple)
    healthy: bool = True
    priority: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillRouteCandidate:
    skill_id: str
    candidate_id: str
    skill_name: str
    skill_version: str
    artifact_hash: str
    capability: str
    runtime_routing_key: str
    runtime_adapter_id: str
    score: float
    usage_count: int
    success_rate: float
    blockers: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityRouteDecision:
    requirement_id: str
    status: CapabilityRouteStatus
    candidates: tuple[SkillRouteCandidate, ...]
    selected: SkillRouteCandidate | None = None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    failure_fingerprint: str | None = None
    decision_id: str = field(default_factory=lambda: new_id("route"))


@dataclass(frozen=True)
class SkillProjectionReceipt:
    skill_id: str
    artifact_hash: str
    runtime_adapter_id: str
    projection_path: str
    projection_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    projection_id: str = field(default_factory=lambda: new_id("skill-projection"))


@dataclass(frozen=True)
class SkillInvocationResult:
    skill_id: str
    runtime_adapter_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    projection: SkillProjectionReceipt | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapabilityExecution:
    requirement: CapabilityRequirement
    decision: CapabilityRouteDecision
    status: CapabilityRouteStatus
    ok: bool
    output: Any = None
    error: str | None = None
    selected_skill_id: str | None = None
    attempts: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    action_result: Any = None
    failure_fingerprint: str | None = None


def capability_requirement_fingerprint(requirement: CapabilityRequirement, *, error: str = "") -> str:
    payload = {
        "capability": requirement.capability,
        "arguments": _json_safe(requirement.arguments),
        "required_runtime_features": sorted(requirement.required_runtime_features),
        "allowed_side_effects": sorted(requirement.allowed_side_effects),
        "error": error.strip(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def scopes_for_side_effects(side_effects: Sequence[str]) -> tuple[ActionScope, ...]:
    scopes = {ActionScope.EXECUTE}
    mapping = {
        "read": ActionScope.READ,
        "write": ActionScope.WRITE,
        "network": ActionScope.NETWORK,
        "memory": ActionScope.MEMORY,
        "execute": ActionScope.EXECUTE,
    }
    for item in side_effects:
        normalized = str(item).strip().lower()
        if normalized in mapping:
            scopes.add(mapping[normalized])
    return tuple(sorted(scopes, key=lambda item: item.value))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@runtime_checkable
class SkillUsageRecorder(Protocol):
    def record_usage(self, usage: SkillUsageEvent) -> SkillUsageEvent: ...


@runtime_checkable
class RuntimeSkillProjector(Protocol):
    @property
    def profile(self) -> RuntimeSkillProfile: ...

    async def project(self, record: SkillRecord) -> SkillProjectionReceipt: ...


@runtime_checkable
class CapabilityExecutionPort(Protocol):
    async def execute(self, requirement: CapabilityRequirement) -> CapabilityExecution: ...
