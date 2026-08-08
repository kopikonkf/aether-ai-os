"""Provider-neutral contracts for governed and resumable actions."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.utils.ids import new_id


class ActionTarget(StrEnum):
    TOOL = "tool"
    RUNTIME = "runtime"


class ActionScope(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    MEMORY = "memory"


class ActionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTING = "executing"
    CONSUMED = "consumed"


@dataclass(frozen=True)
class ActionCapability:
    target: ActionTarget
    operation: str
    description: str
    required_scopes: tuple[ActionScope, ...]
    reversible: bool = True
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    routing_key: str | None = None
    cancel_supported: bool = False


@dataclass(frozen=True)
class ActionProposal:
    target: ActionTarget
    operation: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    required_scopes: tuple[ActionScope, ...] = field(default_factory=tuple)
    reason: str = ""
    risk: ActionRisk = ActionRisk.LOW
    reversible: bool = True
    correlation_id: str | None = None
    retry_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: new_id("act"))


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


def proposal_payload(proposal: ActionProposal) -> dict[str, Any]:
    return {
        "action_id": proposal.action_id,
        "target": proposal.target.value,
        "operation": proposal.operation,
        "arguments": _json_safe(proposal.arguments),
        "required_scopes": [scope.value for scope in proposal.required_scopes],
        "reason": proposal.reason,
        "risk": proposal.risk.value,
        "reversible": proposal.reversible,
        "correlation_id": proposal.correlation_id,
        "retry_reason": proposal.retry_reason,
        "metadata": _json_safe(proposal.metadata),
    }


def canonical_action_hash(proposal: ActionProposal) -> str:
    payload = proposal_payload(proposal)
    payload.pop("correlation_id", None)  # trace-only, not execution semantics
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def proposal_from_payload(payload: Mapping[str, Any]) -> ActionProposal:
    return ActionProposal(
        target=ActionTarget(str(payload["target"])),
        operation=str(payload["operation"]),
        arguments=dict(payload.get("arguments") or {}),
        required_scopes=tuple(ActionScope(str(item)) for item in payload.get("required_scopes") or []),
        reason=str(payload.get("reason") or ""),
        risk=ActionRisk(str(payload.get("risk") or "low")),
        reversible=bool(payload.get("reversible", True)),
        correlation_id=payload.get("correlation_id"),
        retry_reason=payload.get("retry_reason"),
        metadata=dict(payload.get("metadata") or {}),
        action_id=str(payload["action_id"]),
    )


@dataclass(frozen=True)
class ActionApproval:
    """Trusted approval created by an authenticated operator channel.

    The action hash and expiry fields bind an approval to one exact proposal.
    Model output is never accepted as an approval source.
    """

    principal: str
    scopes: tuple[ActionScope, ...]
    reason: str
    approval_id: str = field(default_factory=lambda: new_id("approval"))
    action_hash: str | None = None
    issued_at: str | None = None
    expires_at: str | None = None
    channel: str | None = None


@dataclass(frozen=True)
class ActionDecision:
    approved: bool
    mode: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    decision_id: str = field(default_factory=lambda: new_id("decision"))


@dataclass(frozen=True)
class ActionResult:
    action_id: str
    ok: bool
    status: str
    output: Any = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    failure_fingerprint: str | None = None


@dataclass(frozen=True)
class ActionControlReceipt:
    action_id: str
    control_request_id: str
    status: str
    receipt_id: str
    terminal: bool = False
    replayed: bool = False


@dataclass(frozen=True)
class PendingAction:
    approval_id: str
    action_id: str
    action_hash: str
    status: ApprovalStatus
    proposal: ActionProposal
    requested_at: str
    expires_at: str
    request_channel: str | None = None
    requested_by: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    decision_channel: str | None = None
    consumed_at: str | None = None
    result: ActionResult | None = None
    continuation: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalOutcome:
    pending: PendingAction
    result: ActionResult | None = None
    replayed: bool = False


@runtime_checkable
class ToolExecutor(Protocol):
    async def capabilities(self) -> Sequence[ActionCapability]: ...

    async def execute_tool(self, operation: str, arguments: Mapping[str, Any]): ...


@runtime_checkable
class GovernedActionExecutor(Protocol):
    async def capabilities(self) -> Sequence[ActionCapability]: ...

    async def execute(
        self,
        proposal: ActionProposal,
        approval: ActionApproval | None = None,
    ) -> ActionResult: ...


@runtime_checkable
class ResumableActionExecutor(GovernedActionExecutor, Protocol):
    async def save_continuation(self, approval_id: str, continuation: Mapping[str, Any]) -> None: ...
