"""Governed coding-runtime selection and delegation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from typing import Any, Mapping, Sequence

import yaml

from aether.contracts.actions import (
    ActionApproval, ActionCapability, ActionProposal, ActionResult, ActionRisk,
    ActionScope, ActionTarget, ResumableActionExecutor,
)
from aether.contracts.coding_runtime import (
    CodingEdit, CodingExecution, CodingExecutionStatus, CodingTask,
    RuntimeDescriptor, RuntimeDirectory, RuntimeHealthStatus,
    VerificationCommand, WorkspaceBindingResolver, coding_task_fingerprint,
)
from aether.contracts.event_types import EventType
from aether.events import EventBus


@dataclass(frozen=True)
class CodingRuntimePolicy:
    maximum_attempts: int
    require_healthy: bool
    require_all_capabilities: bool
    require_all_features: bool
    require_binding: bool
    require_session_match: bool
    require_writable_for_edits: bool
    route_operation: str
    body_operation: str
    maximum_edits: int
    maximum_total_bytes: int
    require_verification_for_writes: bool
    fallback_enabled: bool
    do_not_fallback_on_pending_approval: bool
    escalate_on_no_runtime: bool
    escalate_on_all_failures: bool

    @classmethod
    def load(cls) -> "CodingRuntimePolicy":
        path = files("aether.runtimes").joinpath("runtime_adapter_sdk.yaml")
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            maximum_attempts=max(1, int(data["selection"]["maximum_attempts"])),
            require_healthy=bool(data["selection"]["require_healthy"]),
            require_all_capabilities=bool(data["selection"]["require_all_capabilities"]),
            require_all_features=bool(data["selection"]["require_all_features"]),
            require_binding=bool(data["workspace"]["require_binding"]),
            require_session_match=bool(data["workspace"]["require_session_match"]),
            require_writable_for_edits=bool(data["workspace"]["require_writable_for_edits"]),
            route_operation=str(data["execution"]["route_operation"]),
            body_operation=str(data["execution"]["body_operation"]),
            maximum_edits=max(1, int(data["execution"]["maximum_edits"])),
            maximum_total_bytes=max(1, int(data["execution"]["maximum_total_bytes"])),
            require_verification_for_writes=bool(data["execution"]["require_verification_for_writes"]),
            fallback_enabled=bool(data["fallback"]["enabled"]),
            do_not_fallback_on_pending_approval=bool(data["fallback"]["do_not_fallback_on_pending_approval"]),
            escalate_on_no_runtime=bool(data["escalation"]["on_no_runtime"]),
            escalate_on_all_failures=bool(data["escalation"]["on_all_failures"]),
        )


class CodingRuntimeRouter:
    def __init__(
        self,
        directory: RuntimeDirectory,
        bindings: WorkspaceBindingResolver,
        action_executor: ResumableActionExecutor,
        *,
        event_bus: EventBus | None = None,
        policy: CodingRuntimePolicy | None = None,
        dispatch_routing_key: str = "runtime://coding/dispatch",
    ) -> None:
        self.directory = directory
        self.bindings = bindings
        self.action_executor = action_executor
        self.event_bus = event_bus
        self.policy = policy or CodingRuntimePolicy.load()
        self.dispatch_routing_key = dispatch_routing_key

    async def status(self) -> Mapping[str, Any]:
        runtimes = await self.directory.discover()
        return {
            "policy_id": "aether.runtime-adapter-sdk.v1",
            "runtimes": [asdict(item) for item in runtimes],
        }

    async def execute(self, task: CodingTask) -> CodingExecution:
        blockers = self._task_blockers(task)
        if blockers:
            return self._blocked(task, blockers)
        try:
            binding = self.bindings.resolve(task.workspace_id, task.session_id)
        except Exception as exc:
            return self._blocked(task, (f"workspace binding failed: {type(exc).__name__}: {exc}",))
        if self.policy.require_session_match and binding.session_id != task.session_id:
            return self._blocked(task, ("workspace binding session mismatch",))
        if task.edits and self.policy.require_writable_for_edits and not binding.writable:
            return self._blocked(task, ("workspace binding is read-only",))

        delegated = self._emit(EventType.CODING_TASK_DELEGATED, {
            "task_id": task.task_id, "workspace_id": task.workspace_id,
            "session_id": task.session_id, "objective": task.objective,
        }, correlation_id=task.correlation_id)
        descriptors = tuple(await self.directory.discover())
        compatible: list[RuntimeDescriptor] = []
        runtime_blockers: list[str] = []
        for item in descriptors:
            reasons = self._runtime_blockers(task, item)
            if reasons:
                runtime_blockers.extend(f"{item.adapter_id}: {reason}" for reason in reasons)
            else:
                compatible.append(item)
        compatible.sort(key=lambda item: (item.priority, item.adapter_id))
        if not compatible:
            fingerprint = coding_task_fingerprint(task, error="; ".join(runtime_blockers) or "no compatible runtime")
            self._emit(EventType.CODING_RUNTIME_ESCALATED, {
                "task_id": task.task_id, "reason": "no-compatible-runtime",
                "blockers": runtime_blockers, "failure_fingerprint": fingerprint,
            }, severity="warning", correlation_id=task.correlation_id, causation_id=delegated)
            return CodingExecution(task, CodingExecutionStatus.ESCALATED, False,
                                   blockers=tuple(runtime_blockers or ["no compatible coding runtime"]),
                                   failure_fingerprint=fingerprint)

        maximum = self.policy.maximum_attempts if task.allow_fallback and self.policy.fallback_enabled else 1
        selected_descriptors = tuple(compatible[:maximum])
        proposal = ActionProposal(
            target=ActionTarget.RUNTIME,
            operation=self.policy.body_operation,
            arguments={
                "task": _task_payload(task),
                "workspace_binding": asdict(binding),
                "runtime_candidates": [asdict(item) for item in selected_descriptors],
            },
            required_scopes=(ActionScope.READ, ActionScope.WRITE, ActionScope.EXECUTE),
            reason=task.objective,
            risk=ActionRisk.MEDIUM,
            reversible=True,
            correlation_id=task.correlation_id,
            retry_reason=str(task.metadata.get("retry_reason") or "") or None,
            metadata={
                **dict(task.metadata),
                "runtime_id": self.dispatch_routing_key,
                "coding_task_id": task.task_id,
                "workspace_id": task.workspace_id,
                "session_id": task.session_id,
                "runtime_candidate_ids": [item.adapter_id for item in selected_descriptors],
            },
        )
        result = await self.action_executor.execute(proposal)
        if result.status == "pending-approval":
            return CodingExecution(
                task, CodingExecutionStatus.PENDING_APPROVAL, False,
                selected_runtime_id=selected_descriptors[0].adapter_id,
                attempts=({"attempt": 0, "status": "pending-approval", "runtime_candidates": [item.adapter_id for item in selected_descriptors]},),
                action_result=result,
            )
        attempts = tuple(result.metadata.get("runtime_attempts") or ())
        selected_runtime = str(result.metadata.get("selected_runtime_adapter_id") or selected_descriptors[0].adapter_id)
        if result.ok:
            fallback = selected_runtime != selected_descriptors[0].adapter_id
            return CodingExecution(
                task,
                CodingExecutionStatus.FALLBACK_COMPLETED if fallback else CodingExecutionStatus.COMPLETED,
                True,
                selected_runtime_id=selected_runtime,
                result=result.output,
                attempts=attempts,
                action_result=result,
            )
        error = result.error or "coding runtime execution failed"
        fingerprint = result.failure_fingerprint or coding_task_fingerprint(task, error=error)
        self._emit(EventType.CODING_RUNTIME_ESCALATED, {
            "task_id": task.task_id, "reason": "all-runtime-attempts-failed",
            "attempts": list(attempts), "failure_fingerprint": fingerprint,
        }, severity="error", correlation_id=task.correlation_id, causation_id=delegated)
        return CodingExecution(
            task,
            CodingExecutionStatus.ESCALATED if self.policy.escalate_on_all_failures else CodingExecutionStatus.FAILED,
            False,
            selected_runtime_id=selected_runtime,
            attempts=attempts,
            blockers=(error,),
            failure_fingerprint=fingerprint,
            action_result=result,
        )

    def _task_blockers(self, task: CodingTask) -> tuple[str, ...]:
        blockers: list[str] = []
        if not task.objective.strip():
            blockers.append("objective is required")
        if not task.workspace_id.strip() or not task.session_id.strip():
            blockers.append("workspace_id and session_id are required")
        if len(task.edits) > min(task.max_artifacts, self.policy.maximum_edits):
            blockers.append("edit count exceeds policy")
        total = sum(len(item.content.encode("utf-8")) for item in task.edits)
        if total > min(task.max_total_bytes, self.policy.maximum_total_bytes):
            blockers.append("edit bytes exceed policy")
        generates_patch = "coding.patch-generation" in task.required_capabilities or "runtime-generated-patch" in task.required_runtime_features
        if (task.edits or generates_patch) and self.policy.require_verification_for_writes and not task.verification_commands:
            blockers.append("coding task that can change files requires at least one verification command")
        return tuple(blockers)

    def _runtime_blockers(self, task: CodingTask, item: RuntimeDescriptor) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.policy.require_healthy and item.health_status != RuntimeHealthStatus.HEALTHY:
            blockers.append(f"runtime health is {item.health_status.value}")
        if self.policy.body_operation not in item.operations:
            blockers.append(f"runtime does not support {self.policy.body_operation}")
        missing_caps = set(task.required_capabilities) - set(item.capabilities)
        if missing_caps and self.policy.require_all_capabilities:
            blockers.append("missing capabilities: " + ", ".join(sorted(missing_caps)))
        missing_features = set(task.required_runtime_features) - set(item.runtime_features)
        if missing_features and self.policy.require_all_features:
            blockers.append("missing features: " + ", ".join(sorted(missing_features)))
        return tuple(blockers)

    def _blocked(self, task: CodingTask, blockers: Sequence[str]) -> CodingExecution:
        fingerprint = coding_task_fingerprint(task, error="; ".join(blockers))
        self._emit(EventType.CODING_RUNTIME_ESCALATED, {
            "task_id": task.task_id, "reason": "task-blocked",
            "blockers": list(blockers), "failure_fingerprint": fingerprint,
        }, severity="warning", correlation_id=task.correlation_id)
        return CodingExecution(task, CodingExecutionStatus.BLOCKED, False,
                               blockers=tuple(blockers), failure_fingerprint=fingerprint)

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, severity: str = "info",
              correlation_id: str | None = None, causation_id: str | None = None) -> str | None:
        if self.event_bus is None:
            return causation_id
        return self.event_bus.emit(event_type, actor="aether.coding-runtime-router", payload=dict(payload),
                                   severity=severity, correlation_id=correlation_id,
                                   causation_id=causation_id).event_id


class CodingRoutedActionExecutor:
    """Adds model-visible coding delegation while keeping body execution private."""

    def __init__(self, base: ResumableActionExecutor, router: CodingRuntimeRouter) -> None:
        self.base = base
        self.router = router

    async def capabilities(self) -> Sequence[ActionCapability]:
        base = [item for item in await self.base.capabilities() if item.operation != self.router.policy.body_operation]
        base.append(ActionCapability(
            target=ActionTarget.RUNTIME,
            operation=self.router.policy.route_operation,
            description="Delegate a bounded coding task to a governed replaceable runtime body.",
            required_scopes=(), reversible=True,
            input_schema={
                "type": "object",
                "required": ["objective", "workspace_id", "session_id", "edits", "verification_commands"],
                "properties": {
                    "objective": {"type": "string"},
                    "workspace_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "edits": {"type": "array"},
                    "verification_commands": {"type": "array"},
                    "required_runtime_features": {"type": "array"},
                    "allow_fallback": {"type": "boolean"},
                },
            },
        ))
        return tuple(base)

    async def execute(self, proposal: ActionProposal, approval: ActionApproval | None = None) -> ActionResult:
        if proposal.operation != self.router.policy.route_operation:
            return await self.base.execute(proposal, approval)
        args = dict(proposal.arguments)
        task = CodingTask(
            objective=str(args.get("objective") or proposal.reason or ""),
            workspace_id=str(args.get("workspace_id") or ""),
            session_id=str(args.get("session_id") or proposal.metadata.get("session_id") or ""),
            edits=tuple(CodingEdit(str(item.get("path") or ""), str(item.get("content") or ""), item.get("expected_sha256")) for item in args.get("edits") or ()),
            verification_commands=tuple(VerificationCommand(tuple(str(v) for v in item.get("argv") or ()), float(item.get("timeout_seconds", 120.0)), str(item.get("label") or "verification")) for item in args.get("verification_commands") or ()),
            required_capabilities=tuple(str(item) for item in args.get("required_capabilities") or ("coding.edit",)),
            required_runtime_features=tuple(str(item) for item in args.get("required_runtime_features") or ()),
            max_artifacts=int(args.get("max_artifacts", 10)),
            max_total_bytes=int(args.get("max_total_bytes", 262144)),
            allow_fallback=bool(args.get("allow_fallback", True)),
            correlation_id=proposal.correlation_id,
            metadata={**dict(proposal.metadata), "retry_reason": proposal.retry_reason},
        )
        execution = await self.router.execute(task)
        if execution.action_result is not None:
            result = execution.action_result
            return replace(result, metadata={
                **dict(result.metadata), "coding_task_id": task.task_id,
                "coding_status": execution.status.value, "runtime_attempts": list(execution.attempts),
            })
        return ActionResult(proposal.action_id, execution.ok, execution.status.value,
                            output=execution.result, error="; ".join(execution.blockers) or None,
                            failure_fingerprint=execution.failure_fingerprint,
                            metadata={"coding_task_id": task.task_id, "runtime_attempts": list(execution.attempts)})

    async def save_continuation(self, approval_id: str, continuation: Mapping[str, Any]) -> None:
        await self.base.save_continuation(approval_id, continuation)


def _task_payload(task: CodingTask) -> dict[str, Any]:
    return {
        **asdict(task),
        "edits": [asdict(item) for item in task.edits],
        "verification_commands": [asdict(item) for item in task.verification_commands],
    }
