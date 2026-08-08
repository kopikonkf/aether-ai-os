"""Governed action path from proposal through approval and body execution."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
import hashlib
import hmac
import json
from typing import Mapping, Any

from aether.actions.approval import PendingActionStore
from aether.actions.failure import FailureFingerprintStore
from aether.contracts.actions import (
    ActionApproval,
    ActionCapability,
    ActionControlReceipt,
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


class ActionControlError(RuntimeError):
    """Base error for exact-bound cancellation and reconciliation controls."""


class ActionControlConflict(ActionControlError):
    """The requested control cannot be applied to the current action truth."""


class ActionControlIntegrityError(ActionControlError):
    """A control ID, action hash, session, or observed receipt did not bind."""


@dataclass(frozen=True)
class _ActiveExecution:
    proposal: ActionProposal
    task: asyncio.Task[ActionResult]


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
        self._active_executions: dict[str, _ActiveExecution] = {}

    async def capabilities(self) -> list[ActionCapability]:
        capabilities: list[ActionCapability] = []
        if self.tool_executor is not None:
            capabilities.extend(await self.tool_executor.capabilities())
        for runtime_id, runtime in self.runtimes.items():
            if runtime_id in self.hidden_runtime_ids:
                continue
            cancellation_capabilities = await self._runtime_cancellation_capabilities(runtime)
            for operation in sorted(await runtime.capabilities()):
                capabilities.append(ActionCapability(
                    target=ActionTarget.RUNTIME,
                    operation=operation,
                    description=f"Delegate {operation} to runtime adapter {runtime_id}",
                    required_scopes=(ActionScope.EXECUTE,),
                    reversible=True,
                    input_schema={"type": "object"},
                    routing_key=runtime_id,
                    cancel_supported=operation in cancellation_capabilities,
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
        execution_task = asyncio.create_task(
            self._complete_execution(proposal, requested.event_id)
        )
        active = _ActiveExecution(proposal, execution_task)
        self._active_executions[proposal.action_id] = active

        def forget_execution(_: asyncio.Task[ActionResult]) -> None:
            if self._active_executions.get(proposal.action_id) is active:
                self._active_executions.pop(proposal.action_id, None)

        execution_task.add_done_callback(forget_execution)
        # The request waiter is not execution authority. A dropped or timed-out
        # HTTP request must not cancel, replay, or resubmit the governed action.
        return await asyncio.shield(execution_task)

    async def _complete_execution(
        self,
        proposal: ActionProposal,
        requested_event_id: str,
    ) -> ActionResult:
        try:
            backend = await self._dispatch(proposal, requested_event_id)
        except asyncio.CancelledError:
            terminal = self._terminal_event(proposal.action_id)
            if terminal is not None and str(terminal.event_type) == EventType.ACTION_CANCELED.value:
                return ActionResult(
                    proposal.action_id,
                    False,
                    "canceled",
                    metadata={"event_id": terminal.event_id},
                )
            raise
        except Exception as exc:  # adapters may fail, but failure must become evidence
            backend = RuntimeResult(ok=False, error=f"{type(exc).__name__}: {exc}")

        terminal = self._terminal_event(proposal.action_id)
        if terminal is not None and str(terminal.event_type) == EventType.ACTION_CANCELED.value:
            encoded = json.dumps(
                {
                    "ok": backend.ok,
                    "output": str(backend.output),
                    "error": backend.error,
                    "metadata": {str(key): str(value) for key, value in backend.metadata.items()},
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.event_bus.emit(
                EventType.ACTION_LATE_RESULT_DISCARDED,
                actor="aether.action-path",
                payload={
                    "action_id": proposal.action_id,
                    "result_hash": hashlib.sha256(encoded).hexdigest(),
                    "terminal_receipt_id": terminal.event_id,
                },
                severity="warning",
                correlation_id=proposal.correlation_id,
                causation_id=terminal.event_id,
            )
            return ActionResult(
                proposal.action_id,
                False,
                "canceled",
                metadata={"event_id": terminal.event_id, "late_result_discarded": True},
            )

        if backend.ok:
            self.failure_store.resolve_signature(
                proposal,
                resolution=proposal.retry_reason or "execution succeeded",
            )
            completed = self.event_bus.emit(
                EventType.ACTION_COMPLETED,
                actor="aether.action-path",
                payload={
                    "action_id": proposal.action_id,
                    "output": backend.output,
                    "metadata": dict(backend.metadata),
                },
                correlation_id=proposal.correlation_id,
                causation_id=requested_event_id,
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
            payload={
                "action_id": proposal.action_id,
                "error": error,
                "failure_fingerprint": fingerprint,
            },
            severity="error",
            correlation_id=proposal.correlation_id,
            causation_id=requested_event_id,
        )
        self.event_bus.emit(
            EventType.FAILURE_DETECTED,
            actor="aether.action-path",
            payload={
                "action_id": proposal.action_id,
                "failure_fingerprint": fingerprint,
                "operation": proposal.operation,
            },
            severity="warning",
            correlation_id=proposal.correlation_id,
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

    async def cancel_action(
        self,
        action_id: str,
        *,
        control_request_id: str,
        expected_action_hash: str,
        session_id: str,
        principal: str,
        reason: str,
    ) -> ActionControlReceipt:
        if reason != "founder-explicit-cancel":
            raise ActionControlIntegrityError("cancellation requires an explicit founder intent")
        if not str(principal).strip():
            raise ActionControlIntegrityError("cancellation principal is required")
        proposal = self._control_proposal(
            action_id,
            control_request_id=control_request_id,
            expected_action_hash=expected_action_hash,
            session_id=session_id,
        )
        replay = self._control_replay(action_id, control_request_id)
        if replay is not None:
            return replay
        if any(
            str(event.event_type) == EventType.ACTION_CANCEL_INTENT_RECORDED.value
            for event in self._action_events(action_id)
        ):
            raise ActionControlConflict("action already has a cancellation intent")
        terminal = self._terminal_event(action_id)
        if terminal is not None:
            raise ActionControlConflict("terminal action cannot be canceled")
        active = self._active_executions.get(action_id)
        if active is None:
            raise ActionControlConflict(
                "action is not active; reconcile its receipt instead of resubmitting cancel"
            )
        cancel_supported = await self._cancel_supported(proposal)
        terminal = self._terminal_event(action_id)
        if terminal is not None:
            raise ActionControlConflict("action completed while cancel support was checked")
        if self._active_executions.get(action_id) is not active:
            raise ActionControlConflict("action is no longer active")
        intent = self.event_bus.emit(
            EventType.ACTION_CANCEL_INTENT_RECORDED,
            actor="aether.action-control",
            payload=self._control_payload(
                proposal,
                control_request_id=control_request_id,
                session_id=session_id,
                principal=principal,
                extra={"reason": reason, "cancel_supported": cancel_supported},
            ),
            correlation_id=proposal.correlation_id,
        )
        if not cancel_supported:
            unsupported = self.event_bus.emit(
                EventType.ACTION_CANCEL_UNSUPPORTED,
                actor="aether.action-control",
                payload=self._control_payload(
                    proposal,
                    control_request_id=control_request_id,
                    session_id=session_id,
                    principal=principal,
                    extra={"reason": reason},
                ),
                severity="warning",
                correlation_id=proposal.correlation_id,
                causation_id=intent.event_id,
            )
            return ActionControlReceipt(
                action_id, control_request_id, "unsupported", unsupported.event_id
            )
        try:
            cancellation = await self._cancel_backend(proposal)
        except Exception as exc:
            cancellation = RuntimeResult(
                False,
                error=f"{type(exc).__name__}: {exc}",
                metadata={"error_type": type(exc).__name__},
            )
        terminal = self._terminal_event(action_id)
        if terminal is not None:
            return self._terminal_control_receipt(
                terminal,
                control_request_id=control_request_id,
            )
        if not cancellation.ok:
            unconfirmed = self.event_bus.emit(
                EventType.ACTION_CANCEL_NOT_CONFIRMED,
                actor="aether.action-control",
                payload=self._control_payload(
                    proposal,
                    control_request_id=control_request_id,
                    session_id=session_id,
                    principal=principal,
                    extra={"error_type": str(cancellation.metadata.get("error_type") or "CancelNotAcknowledged")},
                ),
                severity="warning",
                correlation_id=proposal.correlation_id,
                causation_id=intent.event_id,
            )
            return ActionControlReceipt(
                action_id, control_request_id, "not-confirmed", unconfirmed.event_id
            )
        requested = self.event_bus.emit(
            EventType.ACTION_CANCEL_REQUESTED,
            actor="aether.action-control",
            payload=self._control_payload(
                proposal,
                control_request_id=control_request_id,
                session_id=session_id,
                principal=principal,
                extra={"reason": reason},
            ),
            correlation_id=proposal.correlation_id,
            causation_id=intent.event_id,
        )
        canceled = self.event_bus.emit(
            EventType.ACTION_CANCELED,
            actor="aether.action-control",
            payload=self._control_payload(
                proposal,
                control_request_id=control_request_id,
                session_id=session_id,
                principal=principal,
                extra={"cancel_acknowledged": True},
            ),
            correlation_id=proposal.correlation_id,
            causation_id=requested.event_id,
        )
        active.task.cancel()
        return ActionControlReceipt(
            action_id,
            control_request_id,
            "canceled",
            canceled.event_id,
            terminal=True,
        )

    async def reconcile_action(
        self,
        action_id: str,
        *,
        control_request_id: str,
        expected_action_hash: str,
        session_id: str,
        principal: str,
        observed_receipt_id: str,
    ) -> ActionControlReceipt:
        if not str(principal).strip():
            raise ActionControlIntegrityError("reconciliation principal is required")
        proposal = self._control_proposal(
            action_id,
            control_request_id=control_request_id,
            expected_action_hash=expected_action_hash,
            session_id=session_id,
        )
        replay = self._control_replay(action_id, control_request_id)
        if replay is not None:
            return replay
        events = self._action_events(action_id)
        if any(
            str(event.event_type) == EventType.ACTION_RECONCILIATION_REQUESTED.value
            for event in events
        ):
            raise ActionControlConflict("action is already reconciling")
        if not any(event.event_id == observed_receipt_id for event in events):
            raise ActionControlIntegrityError(
                "observed action receipt does not belong to the exact action"
            )
        terminal = self._terminal_event(action_id)
        if terminal is not None:
            return self._terminal_control_receipt(
                terminal,
                control_request_id=control_request_id,
            )
        if not any(
            str(event.event_type) == EventType.ACTION_EXECUTION_REQUESTED.value
            for event in events
        ):
            raise ActionControlConflict("action has not reached execution")
        receipt = self.event_bus.emit(
            EventType.ACTION_RECONCILIATION_REQUESTED,
            actor="aether.action-control",
            payload=self._control_payload(
                proposal,
                control_request_id=control_request_id,
                session_id=session_id,
                principal=principal,
                extra={
                    "observed_receipt_id": observed_receipt_id,
                    "outcome": "not-confirmed",
                    "resubmitted": False,
                },
            ),
            severity="warning",
            correlation_id=proposal.correlation_id,
            causation_id=observed_receipt_id,
        )
        return ActionControlReceipt(
            action_id,
            control_request_id,
            "not-confirmed",
            receipt.event_id,
        )

    def _control_proposal(
        self,
        action_id: str,
        *,
        control_request_id: str,
        expected_action_hash: str,
        session_id: str,
    ) -> ActionProposal:
        if not str(control_request_id).strip():
            raise ActionControlIntegrityError("control request ID is required")
        proposed = next(
            (
                event
                for event in self._action_events(action_id)
                if str(event.event_type) == EventType.ACTION_PROPOSED.value
            ),
            None,
        )
        if proposed is None:
            raise ActionControlConflict("action was not found")
        from aether.contracts.actions import canonical_action_hash, proposal_from_payload

        proposal = proposal_from_payload(proposed.payload)
        actual_hash = canonical_action_hash(proposal)
        if not hmac.compare_digest(actual_hash, str(expected_action_hash)):
            raise ActionControlIntegrityError("control action hash mismatch")
        bound_session = str(proposal.metadata.get("session_id") or "")
        if not hmac.compare_digest(bound_session, f"browser:{session_id}"):
            raise ActionControlIntegrityError("control session binding mismatch")
        for event in self.event_bus.replay():
            payload = event.payload
            if str(payload.get("control_request_id") or "") != control_request_id:
                continue
            if (
                str(payload.get("action_id") or "") != action_id
                or not hmac.compare_digest(str(payload.get("action_hash") or ""), actual_hash)
                or not hmac.compare_digest(str(payload.get("session_id") or ""), session_id)
            ):
                raise ActionControlIntegrityError(
                    "control request ID was already bound to different action evidence"
                )
        return proposal

    def _control_replay(
        self,
        action_id: str,
        control_request_id: str,
    ) -> ActionControlReceipt | None:
        matching = [
            event
            for event in self._action_events(action_id)
            if str(event.payload.get("control_request_id") or "") == control_request_id
        ]
        if not matching:
            return None
        terminal = self._terminal_event(action_id)
        if terminal is not None:
            return self._terminal_control_receipt(
                terminal,
                control_request_id=control_request_id,
                replayed=True,
            )
        latest = matching[-1]
        status_by_event = {
            EventType.ACTION_CANCEL_INTENT_RECORDED.value: "requested",
            EventType.ACTION_CANCEL_REQUESTED.value: "canceling",
            EventType.ACTION_CANCEL_UNSUPPORTED.value: "unsupported",
            EventType.ACTION_CANCEL_NOT_CONFIRMED.value: "not-confirmed",
            EventType.ACTION_RECONCILIATION_REQUESTED.value: "not-confirmed",
        }
        return ActionControlReceipt(
            action_id,
            control_request_id,
            status_by_event.get(str(latest.event_type), "not-confirmed"),
            latest.event_id,
            replayed=True,
        )

    def _terminal_control_receipt(
        self,
        event: Any,
        *,
        control_request_id: str,
        replayed: bool = False,
    ) -> ActionControlReceipt:
        statuses = {
            EventType.ACTION_COMPLETED.value: "succeeded",
            EventType.ACTION_FAILED.value: "failed",
            EventType.ACTION_CANCELED.value: "canceled",
            EventType.ACTION_PREFLIGHT_FAILED.value: "unavailable",
            EventType.GOVERNANCE_REJECTED.value: "rejected",
            EventType.APPROVAL_REJECTED.value: "rejected",
            EventType.APPROVAL_EXPIRED.value: "rejected",
            EventType.ACTION_RETRY_BLOCKED.value: "rejected",
        }
        return ActionControlReceipt(
            str(event.payload.get("action_id") or ""),
            control_request_id,
            statuses[str(event.event_type)],
            event.event_id,
            terminal=True,
            replayed=replayed,
        )

    def _action_events(self, action_id: str) -> list[Any]:
        return [
            event
            for event in self.event_bus.replay()
            if str(event.payload.get("action_id") or "") == action_id
        ]

    def _terminal_event(self, action_id: str) -> Any | None:
        terminal_types = {
            EventType.ACTION_COMPLETED.value,
            EventType.ACTION_FAILED.value,
            EventType.ACTION_CANCELED.value,
            EventType.ACTION_PREFLIGHT_FAILED.value,
            EventType.GOVERNANCE_REJECTED.value,
            EventType.APPROVAL_REJECTED.value,
            EventType.APPROVAL_EXPIRED.value,
            EventType.ACTION_RETRY_BLOCKED.value,
        }
        return next(
            (
                event
                for event in reversed(self._action_events(action_id))
                if str(event.event_type) in terminal_types
            ),
            None,
        )

    @staticmethod
    def _control_payload(
        proposal: ActionProposal,
        *,
        control_request_id: str,
        session_id: str,
        principal: str,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        from aether.contracts.actions import canonical_action_hash

        return {
            "action_id": proposal.action_id,
            "action_hash": canonical_action_hash(proposal),
            "control_request_id": control_request_id,
            "session_id": session_id,
            "principal": principal,
            **dict(extra or {}),
        }

    async def _cancel_supported(self, proposal: ActionProposal) -> bool:
        if proposal.target == ActionTarget.TOOL:
            if self.tool_executor is None or not callable(getattr(self.tool_executor, "cancel_tool", None)):
                return False
            return any(
                capability.target == proposal.target
                and capability.operation == proposal.operation
                and capability.cancel_supported
                for capability in await self.tool_executor.capabilities()
            )
        if proposal.target == ActionTarget.RUNTIME:
            runtime_id = str(proposal.metadata.get("runtime_id") or "default")
            runtime = self.runtimes.get(runtime_id)
            if runtime is None:
                return False
            return proposal.operation in await self._runtime_cancellation_capabilities(runtime)
        return False

    @staticmethod
    async def _runtime_cancellation_capabilities(runtime: RuntimeAdapter) -> set[str]:
        declaration = getattr(runtime, "cancellation_capabilities", None)
        if not callable(declaration) or not callable(getattr(runtime, "cancel", None)):
            return set()
        return {str(operation) for operation in await declaration()}

    async def _cancel_backend(self, proposal: ActionProposal) -> RuntimeResult:
        if proposal.target == ActionTarget.TOOL and self.tool_executor is not None:
            return await self.tool_executor.cancel_tool(
                proposal.action_id,
                proposal.operation,
                proposal.arguments,
            )
        if proposal.target == ActionTarget.RUNTIME:
            runtime_id = str(proposal.metadata.get("runtime_id") or "default")
            runtime = self.runtimes.get(runtime_id)
            if runtime is not None and callable(getattr(runtime, "cancel", None)):
                return await runtime.cancel(RuntimeCommand(
                    command=proposal.operation,
                    arguments=proposal.arguments,
                    capability=proposal.operation,
                    correlation_id=proposal.correlation_id,
                ))
        return RuntimeResult(False, error="Cancellation is unsupported")


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
