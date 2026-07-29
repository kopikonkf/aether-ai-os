"""Governed capability router for active Aether-owned skills."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from typing import Any, Mapping, Sequence

import yaml

from aether.contracts.actions import (
    ActionApproval,
    ActionCapability,
    ActionProposal,
    ActionResult,
    ActionRisk,
    ActionTarget,
    GovernedActionExecutor,
    ResumableActionExecutor,
)
from aether.contracts.capabilities import (
    CapabilityExecution,
    CapabilityRequirement,
    CapabilityRouteDecision,
    CapabilityRouteStatus,
    RuntimeSkillProfile,
    SkillRouteCandidate,
    capability_requirement_fingerprint,
    scopes_for_side_effects,
)
from aether.contracts.event_types import EventType
from aether.contracts.skills import SkillLifecycleStatus
from aether.events import EventBus
from aether.skills.store import SQLiteSkillStore


_RISK_ORDER = {
    ActionRisk.LOW: 0,
    ActionRisk.MEDIUM: 1,
    ActionRisk.HIGH: 2,
    ActionRisk.CRITICAL: 3,
}


@dataclass(frozen=True)
class CapabilityRouterPolicy:
    maximum_attempts: int
    success_rate_weight: float
    require_healthy_runtime: bool
    require_all_runtime_features: bool
    require_all_side_effects_supported: bool
    require_input_schema_validation: bool
    require_output_schema_validation: bool
    fallback_enabled: bool
    do_not_fallback_on_pending_approval: bool
    action_operation: str

    @classmethod
    def load(cls) -> "CapabilityRouterPolicy":
        path = files("aether.capabilities").joinpath("capability_router.yaml")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        matching = data["matching"]
        compatibility = data["compatibility"]
        fallback = data["fallback"]
        execution = data["execution"]
        return cls(
            maximum_attempts=max(1, int(matching["maximum_attempts"])),
            success_rate_weight=float(matching["minimum_success_rate_weight"]),
            require_healthy_runtime=bool(compatibility["require_healthy_runtime"]),
            require_all_runtime_features=bool(compatibility["require_all_runtime_features"]),
            require_all_side_effects_supported=bool(compatibility["require_all_side_effects_supported"]),
            require_input_schema_validation=bool(compatibility["require_input_schema_validation"]),
            require_output_schema_validation=bool(compatibility["require_output_schema_validation"]),
            fallback_enabled=bool(fallback["enabled"]),
            do_not_fallback_on_pending_approval=bool(fallback["do_not_fallback_on_pending_approval"]),
            action_operation=str(execution["action_operation"]),
        )


class CapabilityRouterBlocked(RuntimeError):
    def __init__(self, blockers: Sequence[str]):
        self.blockers = tuple(blockers)
        super().__init__("capability router blocked: " + "; ".join(self.blockers))


class CapabilityRouter:
    """Selects active skills by capability and delegates execution to governance.

    The router never imports a runtime implementation. Runtime compatibility is
    represented by opaque profiles supplied by Gateway adapters.
    """

    def __init__(
        self,
        store: SQLiteSkillStore,
        action_executor: GovernedActionExecutor,
        runtime_profiles: Sequence[RuntimeSkillProfile],
        *,
        event_bus: EventBus | None = None,
        policy: CapabilityRouterPolicy | None = None,
    ) -> None:
        self.store = store
        self.action_executor = action_executor
        self.runtime_profiles = tuple(runtime_profiles)
        self.event_bus = event_bus
        self.policy = policy or CapabilityRouterPolicy.load()

    def route(self, requirement: CapabilityRequirement) -> CapabilityRouteDecision:
        required = requirement.capability.strip()
        if not required:
            fingerprint = capability_requirement_fingerprint(requirement, error="empty capability")
            return CapabilityRouteDecision(
                requirement.requirement_id,
                CapabilityRouteStatus.BLOCKED,
                (),
                blockers=("capability is required",),
                failure_fingerprint=fingerprint,
            )

        candidates: list[SkillRouteCandidate] = []
        global_blockers: list[str] = []
        records = self.store.list_records(limit=5000)
        for record in records:
            if record.lifecycle_status != SkillLifecycleStatus.ACTIVE:
                continue
            if required not in record.manifest.usage.capabilities:
                continue
            input_errors = _validate_schema(requirement.arguments, record.manifest.usage.input_schema, path="input")
            if input_errors and self.policy.require_input_schema_validation:
                global_blockers.extend(f"{record.skill_id}: {item}" for item in input_errors)
                continue
            for profile in self.runtime_profiles:
                blockers = self._compatibility_blockers(record, requirement, profile)
                usages = self.store.usages(record.skill_id)
                usage_count = len(usages)
                success_rate = sum(item.success for item in usages) / usage_count if usage_count else 0.5
                score = 1.0 + (success_rate * self.policy.success_rate_weight) - (profile.priority / 100000.0)
                candidates.append(SkillRouteCandidate(
                    skill_id=record.skill_id,
                    candidate_id=record.candidate_id,
                    skill_name=record.manifest.name,
                    skill_version=record.manifest.version,
                    artifact_hash=record.artifact_hash,
                    capability=required,
                    runtime_routing_key=profile.routing_key,
                    runtime_adapter_id=profile.adapter_id,
                    score=score,
                    usage_count=usage_count,
                    success_rate=success_rate,
                    blockers=blockers,
                    metadata={
                        "runtime_features": list(profile.runtime_features),
                        "side_effects": list(record.manifest.usage.side_effects),
                    },
                ))

        candidates.sort(key=lambda item: (-int(not item.blockers), -item.score, item.skill_name, item.skill_id))
        compatible = tuple(item for item in candidates if not item.blockers)
        if not compatible:
            status = CapabilityRouteStatus.BLOCKED if (candidates or global_blockers) else CapabilityRouteStatus.NOT_FOUND
            blockers = tuple(dict.fromkeys(global_blockers + [b for item in candidates for b in item.blockers]))
            if not blockers:
                blockers = (f"no active compatible skill provides capability {required}",)
            fingerprint = capability_requirement_fingerprint(requirement, error="; ".join(blockers))
            return CapabilityRouteDecision(
                requirement.requirement_id,
                status,
                tuple(candidates),
                blockers=blockers,
                failure_fingerprint=fingerprint,
            )
        return CapabilityRouteDecision(
            requirement.requirement_id,
            CapabilityRouteStatus.SELECTED,
            tuple(candidates),
            selected=compatible[0],
        )

    async def execute(self, requirement: CapabilityRequirement) -> CapabilityExecution:
        required_event = self._emit(
            EventType.CAPABILITY_REQUIRED,
            {
                "requirement_id": requirement.requirement_id,
                "capability": requirement.capability,
                "required_runtime_features": list(requirement.required_runtime_features),
                "allowed_side_effects": list(requirement.allowed_side_effects),
            },
            correlation_id=requirement.correlation_id,
        )
        decision = self.route(requirement)
        if decision.selected is None:
            self._emit(
                EventType.SKILL_ROUTE_BLOCKED,
                {
                    "requirement_id": requirement.requirement_id,
                    "status": decision.status.value,
                    "blockers": list(decision.blockers),
                    "failure_fingerprint": decision.failure_fingerprint,
                },
                severity="warning",
                correlation_id=requirement.correlation_id,
                causation_id=required_event,
            )
            return CapabilityExecution(
                requirement,
                decision,
                decision.status,
                False,
                error="; ".join(decision.blockers),
                failure_fingerprint=decision.failure_fingerprint,
            )

        compatible = [item for item in decision.candidates if not item.blockers]
        maximum = self.policy.maximum_attempts if requirement.allow_fallback and self.policy.fallback_enabled else 1
        attempts: list[Mapping[str, Any]] = []
        last_result: ActionResult | None = None
        selected_skill_id: str | None = None
        for index, selected in enumerate(compatible[:maximum]):
            selected_skill_id = selected.skill_id
            selected_event = self._emit(
                EventType.SKILL_ROUTE_SELECTED if index == 0 else EventType.SKILL_FALLBACK_SELECTED,
                {
                    "requirement_id": requirement.requirement_id,
                    "skill_id": selected.skill_id,
                    "candidate_id": selected.candidate_id,
                    "runtime_adapter_id": selected.runtime_adapter_id,
                    "score": selected.score,
                    "attempt": index + 1,
                },
                correlation_id=requirement.correlation_id,
                causation_id=required_event,
            )
            record = self.store.get_record(selected.skill_id)
            side_effects = tuple(record.manifest.usage.side_effects)
            proposal = ActionProposal(
                target=ActionTarget.RUNTIME,
                operation=self.policy.action_operation,
                arguments={
                    "skill_id": record.skill_id,
                    "artifact_hash": record.artifact_hash,
                    "capability": requirement.capability,
                    "input": dict(requirement.arguments),
                    "requirement_id": requirement.requirement_id,
                },
                required_scopes=scopes_for_side_effects(side_effects),
                reason=requirement.reason.strip() or f"Execute active Aether skill for capability {requirement.capability}",
                risk=_derived_risk(requirement.risk, side_effects),
                reversible=requirement.reversible and not bool(set(side_effects) & {"write", "network", "memory"}),
                correlation_id=requirement.correlation_id,
                retry_reason=str(requirement.metadata.get("retry_reason") or "") or None,
                metadata={
                    **dict(requirement.metadata),
                    "runtime_id": selected.runtime_routing_key,
                    "skill_id": selected.skill_id,
                    "skill_artifact_hash": selected.artifact_hash,
                    "capability_requirement_id": requirement.requirement_id,
                    "session_id": requirement.session_id,
                    "route_event_id": selected_event,
                },
            )
            result = await self.action_executor.execute(proposal)
            last_result = result
            attempts.append({
                "attempt": index + 1,
                "skill_id": selected.skill_id,
                "runtime_adapter_id": selected.runtime_adapter_id,
                "action_id": result.action_id,
                "ok": result.ok,
                "status": result.status,
                "failure_fingerprint": result.failure_fingerprint,
            })
            if result.status == "pending-approval" and self.policy.do_not_fallback_on_pending_approval:
                return CapabilityExecution(
                    requirement,
                    replace(decision, status=CapabilityRouteStatus.PENDING_APPROVAL, selected=selected),
                    CapabilityRouteStatus.PENDING_APPROVAL,
                    False,
                    error=result.error,
                    selected_skill_id=selected.skill_id,
                    attempts=tuple(attempts),
                    action_result=result,
                )
            if result.ok:
                status = CapabilityRouteStatus.COMPLETED if index == 0 else CapabilityRouteStatus.FALLBACK_COMPLETED
                self._emit(
                    EventType.SKILL_EXECUTION_VERIFIED,
                    {
                        "requirement_id": requirement.requirement_id,
                        "skill_id": selected.skill_id,
                        "runtime_adapter_id": selected.runtime_adapter_id,
                        "action_id": result.action_id,
                        "fallback": index > 0,
                    },
                    correlation_id=requirement.correlation_id,
                    causation_id=str(result.metadata.get("event_id") or selected_event),
                )
                return CapabilityExecution(
                    requirement,
                    replace(decision, status=status, selected=selected),
                    status,
                    True,
                    output=result.output,
                    selected_skill_id=selected.skill_id,
                    attempts=tuple(attempts),
                    action_result=result,
                )

        error = last_result.error if last_result else "No compatible skill execution was attempted"
        fingerprint = (
            last_result.failure_fingerprint if last_result and last_result.failure_fingerprint
            else capability_requirement_fingerprint(requirement, error=error or "skill execution failed")
        )
        self._emit(
            EventType.SKILL_EXECUTION_FAILED,
            {
                "requirement_id": requirement.requirement_id,
                "selected_skill_id": selected_skill_id,
                "attempts": attempts,
                "error": error,
                "failure_fingerprint": fingerprint,
            },
            severity="error",
            correlation_id=requirement.correlation_id,
            causation_id=required_event,
        )
        return CapabilityExecution(
            requirement,
            replace(decision, status=CapabilityRouteStatus.FAILED),
            CapabilityRouteStatus.FAILED,
            False,
            error=error,
            selected_skill_id=selected_skill_id,
            attempts=tuple(attempts),
            action_result=last_result,
            failure_fingerprint=fingerprint,
        )

    def _compatibility_blockers(self, record, requirement: CapabilityRequirement, profile: RuntimeSkillProfile) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.policy.require_healthy_runtime and not profile.healthy:
            blockers.append(f"runtime adapter is unhealthy: {profile.adapter_id}")
        if self.policy.action_operation not in profile.operations:
            blockers.append(f"runtime does not support {self.policy.action_operation}: {profile.adapter_id}")
        required_features = set(requirement.required_runtime_features) | set(record.manifest.usage.runtime_requirements)
        missing_features = required_features - set(profile.runtime_features)
        if missing_features and self.policy.require_all_runtime_features:
            blockers.append("runtime missing features: " + ", ".join(sorted(missing_features)))
        side_effects = set(record.manifest.usage.side_effects)
        unsupported = side_effects - set(profile.supported_side_effects)
        if unsupported and self.policy.require_all_side_effects_supported:
            blockers.append("runtime does not support side effects: " + ", ".join(sorted(unsupported)))
        if requirement.allowed_side_effects:
            disallowed = side_effects - set(requirement.allowed_side_effects)
            if disallowed:
                blockers.append("skill requests disallowed side effects: " + ", ".join(sorted(disallowed)))
        return tuple(blockers)

    def _emit(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
        *,
        severity: str = "info",
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> str | None:
        if self.event_bus is None:
            return causation_id
        return self.event_bus.emit(
            event_type,
            actor="aether.capability-router",
            payload=dict(payload),
            severity=severity,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ).event_id


class RoutedActionExecutor:
    """Adds capability routing to an existing governed action executor.

    Direct ``skill.execute`` capability is hidden from model providers. Models
    can request ``capability.route``; the router then creates the exact governed
    skill action after selecting an active compatible skill.
    """

    ROUTE_OPERATION = "capability.route"

    def __init__(self, base: ResumableActionExecutor, router: CapabilityRouter) -> None:
        self.base = base
        self.router = router

    async def capabilities(self) -> Sequence[ActionCapability]:
        base = [item for item in await self.base.capabilities() if item.operation != self.router.policy.action_operation]
        base.append(ActionCapability(
            target=ActionTarget.RUNTIME,
            operation=self.ROUTE_OPERATION,
            description="Route a capability requirement to an active governed Aether skill.",
            required_scopes=(),
            reversible=True,
            input_schema={
                "type": "object",
                "required": ["capability", "input"],
                "properties": {
                    "capability": {"type": "string"},
                    "input": {"type": "object"},
                    "required_runtime_features": {"type": "array"},
                    "allowed_side_effects": {"type": "array"},
                    "allow_fallback": {"type": "boolean"},
                },
            },
        ))
        return tuple(base)

    async def execute(self, proposal: ActionProposal, approval: ActionApproval | None = None) -> ActionResult:
        if proposal.operation != self.ROUTE_OPERATION:
            return await self.base.execute(proposal, approval)
        arguments = dict(proposal.arguments)
        requirement = CapabilityRequirement(
            capability=str(arguments.get("capability") or ""),
            arguments=dict(arguments.get("input") or {}),
            required_runtime_features=tuple(str(item) for item in arguments.get("required_runtime_features") or ()),
            allowed_side_effects=tuple(str(item) for item in arguments.get("allowed_side_effects") or ()),
            reason=proposal.reason,
            risk=proposal.risk,
            reversible=proposal.reversible,
            allow_fallback=bool(arguments.get("allow_fallback", True)),
            session_id=str(proposal.metadata.get("session_id") or "") or None,
            correlation_id=proposal.correlation_id,
            metadata={**dict(proposal.metadata), "retry_reason": proposal.retry_reason},
        )
        execution = await self.router.execute(requirement)
        if execution.action_result is not None:
            result = execution.action_result
            return replace(result, metadata={
                **dict(result.metadata),
                "capability_requirement_id": requirement.requirement_id,
                "route_status": execution.status.value,
                "selected_skill_id": execution.selected_skill_id,
                "route_attempts": list(execution.attempts),
            })
        return ActionResult(
            proposal.action_id,
            execution.ok,
            execution.status.value,
            output=execution.output,
            error=execution.error,
            failure_fingerprint=execution.failure_fingerprint,
            metadata={
                "capability_requirement_id": requirement.requirement_id,
                "route_status": execution.status.value,
                "selected_skill_id": execution.selected_skill_id,
                "route_attempts": list(execution.attempts),
            },
        )

    async def save_continuation(self, approval_id: str, continuation: Mapping[str, Any]) -> None:
        await self.base.save_continuation(approval_id, continuation)


def _derived_risk(requested: ActionRisk, side_effects: Sequence[str]) -> ActionRisk:
    derived = ActionRisk.LOW
    normalized = set(side_effects)
    if normalized & {"write", "memory"}:
        derived = ActionRisk.MEDIUM
    if "network" in normalized:
        derived = ActionRisk.HIGH
    return requested if _RISK_ORDER[requested] >= _RISK_ORDER[derived] else derived


def _validate_schema(value: Any, schema: Mapping[str, Any], *, path: str) -> tuple[str, ...]:
    if not schema:
        return ()
    errors: list[str] = []
    expected = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected in type_map and not isinstance(value, type_map[expected]):
        return (f"{path} must be {expected}",)
    if expected == "object" and isinstance(value, Mapping):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} is required")
        properties = schema.get("properties") or {}
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, Mapping):
                errors.extend(_validate_schema(value[key], child_schema, path=f"{path}.{key}"))
    if expected == "array" and isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            errors.extend(_validate_schema(item, schema["items"], path=f"{path}[{index}]"))
    return tuple(errors)
