"""Governed action path from proposal through approval and body execution."""
from __future__ import annotations

from dataclasses import asdict, replace
from typing import Mapping, Any

from aether.actions.approval import PendingActionStore
from aether.actions.failure import FailureFingerprintStore
from aether.contracts.actions import (
    ActionApproval,
    ActionCapability,
    ActionProposal,
    ActionResult,
    ActionScope,
    ActionTarget,
    ToolExecutor,
)
from aether.contracts.event_types import EventType
from aether.contracts.runtime import RuntimeAdapter, RuntimeCommand, RuntimeResult
from aether.events import EventBus
from aether.governance.actions import ActionGovernor
from aether.utils.ids import new_id


class GovernedActionPath:
    def __init__(
        self,
        event_bus: EventBus,
        governor: ActionGovernor,
        failure_store: FailureFingerprintStore,
        *,
        tool_executor: ToolExecutor | None = None,
        runtimes: Mapping[str, RuntimeAdapter] | None = None,
        pending_store: PendingActionStore | None = None,
        approval_ttl_seconds: int = 900,
        hidden_runtime_ids: set[str] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.governor = governor
        self.failure_store = failure_store
        self.tool_executor = tool_executor
        self.runtimes = dict(runtimes or {})
        self.pending_store = pending_store
        self.approval_ttl_seconds = max(1, int(approval_ttl_seconds))
        self.hidden_runtime_ids = set(hidden_runtime_ids or set())

    async def capabilities(self) -> list[ActionCapability]:
        capabilities: list[ActionCapability] = []
        if self.tool_executor is not None:
            capabilities.extend(await self.tool_executor.capabilities())
        for runtime_id, runtime in self.runtimes.items():
            if runtime_id in self.hidden_runtime_ids:
                continue
            for operation in sorted(await runtime.capabilities()):
                capabilities.append(ActionCapability(
                    target=ActionTarget.RUNTIME,
                    operation=operation,
                    description=f"Delegate {operation} to runtime adapter {runtime_id}",
                    required_scopes=(ActionScope.EXECUTE,),
                    reversible=True,
                    input_schema={"type": "object"},
                    routing_key=runtime_id,
                ))
        return capabilities

    async def save_continuation(self, approval_id: str, continuation: Mapping[str, Any]) -> None:
        if self.pending_store is None:
            raise RuntimeError("No pending action store is configured")
        self.pending_store.save_continuation(approval_id, continuation)

    async def execute(self, proposal: ActionProposal, approval: ActionApproval | None = None) -> ActionResult:
        correlation_id = proposal.correlation_id or new_id("corr")
        proposal = replace(proposal, correlation_id=correlation_id)
        proposed = self.event_bus.emit(
            EventType.ACTION_PROPOSED,
            actor="aether.action-path",
            payload={
                **asdict(proposal),
                "target": str(proposal.target),
                "risk": str(proposal.risk),
                "required_scopes": [str(scope) for scope in proposal.required_scopes],
            },
            correlation_id=correlation_id,
        )

        preflight = await self._preflight(proposal, proposed.event_id)
        if preflight is not None:
            return preflight

        prior = self.failure_store.open_failures(proposal)
        if prior and not (proposal.retry_reason or "").strip():
            blocked = self.event_bus.emit(
                EventType.ACTION_RETRY_BLOCKED,
                actor="aether.action-path",
                payload={"action_id": proposal.action_id, "prior_fingerprints": [row["fingerprint"] for row in prior]},
                severity="warning",
                correlation_id=correlation_id,
                causation_id=proposed.event_id,
            )
            return ActionResult(
                proposal.action_id,
                False,
                "retry-blocked",
                error="An unresolved identical failure exists; explicit retry_reason is required.",
                metadata={"event_id": blocked.event_id, "prior_fingerprints": [row["fingerprint"] for row in prior]},
            )

        decision = self.governor.review(proposal, approval)
        if decision.approved:
            governance_type = EventType.GOVERNANCE_APPROVED
        elif decision.mode == "approval-required":
            governance_type = EventType.GOVERNANCE_APPROVAL_REQUIRED
        else:
            governance_type = EventType.GOVERNANCE_REJECTED
        governance = self.event_bus.emit(
            governance_type,
            actor="aether.governance",
            payload={"action_id": proposal.action_id, **asdict(decision)},
            severity="info" if decision.approved else "warning",
            correlation_id=correlation_id,
            causation_id=proposed.event_id,
        )
        if not decision.approved:
            if decision.mode == "approval-required" and self.pending_store is not None:
                metadata = dict(proposal.metadata)
                pending, created = self.pending_store.create_or_get(
                    proposal,
                    request_channel=str(metadata.get("channel") or "unknown"),
                    requested_by=str(metadata.get("user_id") or metadata.get("session_id") or proposal.reason),
                    request_event_id=governance.event_id,
                    ttl_seconds=self.approval_ttl_seconds,
                )
                if created:
                    requested = self.event_bus.emit(
                        EventType.APPROVAL_REQUESTED,
                        actor="aether.action-path",
                        payload={
                            "approval_id": pending.approval_id,
                            "action_id": pending.action_id,
                            "action_hash": pending.action_hash,
                            "target": pending.proposal.target.value,
                            "operation": pending.proposal.operation,
                            "reason": pending.proposal.reason,
                            "risk": pending.proposal.risk.value,
                            "required_scopes": [scope.value for scope in pending.proposal.required_scopes],
                            "expires_at": pending.expires_at,
                            "request_channel": pending.request_channel,
                        },
                        severity="warning",
                        correlation_id=correlation_id,
                        causation_id=governance.event_id,
                    )
                else:
                    requested = governance
                return ActionResult(
                    proposal.action_id,
                    False,
                    "pending-approval",
                    error="Trusted operator approval is required.",
                    metadata={
                        "decision_id": decision.decision_id,
                        "approval_id": pending.approval_id,
                        "action_hash": pending.action_hash,
                        "expires_at": pending.expires_at,
                        "approval_event_id": requested.event_id,
                        "created": created,
                    },
                )
            return ActionResult(
                proposal.action_id,
                False,
                decision.mode,
                error="; ".join(decision.reasons),
                metadata={"decision_id": decision.decision_id},
            )

        requested = self.event_bus.emit(
            EventType.ACTION_EXECUTION_REQUESTED,
            actor="aether.action-path",
            payload={"action_id": proposal.action_id, "target": str(proposal.target), "operation": proposal.operation},
            correlation_id=correlation_id,
            causation_id=governance.event_id,
        )
        try:
            backend = await self._dispatch(proposal, requested.event_id)
        except Exception as exc:  # adapters may fail, but failure must become evidence
            backend = RuntimeResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        if backend.ok:
            self.failure_store.resolve_signature(proposal, resolution=proposal.retry_reason or "execution succeeded")
            completed = self.event_bus.emit(
                EventType.ACTION_COMPLETED,
                actor="aether.action-path",
                payload={"action_id": proposal.action_id, "output": backend.output, "metadata": dict(backend.metadata)},
                correlation_id=correlation_id,
                causation_id=requested.event_id,
            )
            return ActionResult(
                proposal.action_id,
                True,
                "completed",
                output=backend.output,
                metadata={**dict(backend.metadata), "event_id": completed.event_id},
            )

        error = backend.error or "Action backend returned failure"
        fingerprint = self.failure_store.record(
            proposal,
            error_type=str(backend.metadata.get("error_type") or "BackendFailure"),
            error=error,
        )
        failed = self.event_bus.emit(
            EventType.ACTION_FAILED,
            actor="aether.action-path",
            payload={"action_id": proposal.action_id, "error": error, "failure_fingerprint": fingerprint},
            severity="error",
            correlation_id=correlation_id,
            causation_id=requested.event_id,
        )
        self.event_bus.emit(
            EventType.FAILURE_DETECTED,
            actor="aether.action-path",
            payload={"action_id": proposal.action_id, "failure_fingerprint": fingerprint, "operation": proposal.operation},
            severity="warning",
            correlation_id=correlation_id,
            causation_id=failed.event_id,
        )
        return ActionResult(
            proposal.action_id,
            False,
            "failed",
            error=error,
            metadata=dict(backend.metadata),
            failure_fingerprint=fingerprint,
        )


    async def _preflight(self, proposal: ActionProposal, causation_id: str) -> ActionResult | None:
        """Reject impossible tool actions before requesting trusted approval."""
        if proposal.target != ActionTarget.TOOL or self.tool_executor is None:
            return None
        validator = getattr(self.tool_executor, "validate_tool", None)
        if validator is None:
            return None
        try:
            result = await validator(proposal.operation, proposal.arguments)
        except Exception as exc:
            result = RuntimeResult(False, error=f"{type(exc).__name__}: {exc}", metadata={"error_type": type(exc).__name__})
        if result.ok:
            return None
        error = result.error or "Tool action failed preflight validation."
        event = self.event_bus.emit(
            EventType.ACTION_PREFLIGHT_FAILED,
            actor="aether.action-path",
            payload={
                "action_id": proposal.action_id,
                "target": proposal.target.value,
                "operation": proposal.operation,
                "error": error,
                "metadata": dict(result.metadata),
            },
            severity="warning",
            correlation_id=proposal.correlation_id,
            causation_id=causation_id,
        )
        return ActionResult(
            proposal.action_id,
            False,
            "preflight-failed",
            error=error,
            metadata={**dict(result.metadata), "event_id": event.event_id},
        )

    async def _dispatch(self, proposal: ActionProposal, causation_id: str) -> RuntimeResult:
        if proposal.target == ActionTarget.TOOL:
            if self.tool_executor is None:
                return RuntimeResult(False, error="No tool executor configured")
            return await self.tool_executor.execute_tool(proposal.operation, proposal.arguments)
        if proposal.target == ActionTarget.RUNTIME:
            runtime_id = str(proposal.metadata.get("runtime_id") or "default")
            runtime = self.runtimes.get(runtime_id)
            if runtime is None:
                return RuntimeResult(False, error=f"Unknown runtime adapter: {runtime_id}")
            requested = self.event_bus.emit(
                EventType.RUNTIME_COMMAND_REQUESTED,
                actor="aether.action-path",
                payload={"action_id": proposal.action_id, "runtime_id": runtime_id, "command": proposal.operation},
                correlation_id=proposal.correlation_id,
                causation_id=causation_id,
            )
            result = await runtime.execute(RuntimeCommand(
                command=proposal.operation,
                arguments=proposal.arguments,
                capability=proposal.operation,
                correlation_id=proposal.correlation_id,
            ))
            self.event_bus.emit(
                EventType.RUNTIME_RESULT_RECEIVED,
                actor=runtime.adapter_id,
                payload={"action_id": proposal.action_id, "ok": result.ok, "error": result.error, "metadata": dict(result.metadata)},
                severity="info" if result.ok else "error",
                correlation_id=proposal.correlation_id,
                causation_id=requested.event_id,
            )
            return result
        return RuntimeResult(False, error=f"Unsupported action target: {proposal.target}")
