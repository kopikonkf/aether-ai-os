"""APCB contracts — durable coordination identity, receipts, handoff, prompt envelope.

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Sections 5 (durable identity), 6 (state machine), 9 (prompt envelope),
10 (handoff), 13 (service identity), 14 (evidence normalization).

These are pure data contracts: no Herdr calls, no Aether service calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aether.utils.ids import new_id


# ---------------------------------------------------------------------------
# Durable coordination identity (contract section 5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReceiptIdempotencyKey:
    """(mission_id, work_id, attempt_number, principal_id) — the APCB
    ExecutionIdentity canonical tuple (P2-F01).

    Every APCB receipt is keyed by the full ExecutionIdentity so the same
    WORK-X attempt-1 on two different missions are distinct executions and
    never collide (cross-mission idempotency isolation).
    """

    mission_id: str
    work_id: str
    attempt_number: int
    principal_id: str

    def as_tuple(self) -> tuple[str, str, int, str]:
        return (self.mission_id, self.work_id, self.attempt_number, self.principal_id)

    def __str__(self) -> str:
        return f"{self.mission_id}/{self.work_id}#{self.attempt_number}@{self.principal_id}"


def execution_receipt_key(
    mission_id: str, work_id: str, attempt_number: int, principal_id: str
) -> ReceiptIdempotencyKey:
    return ReceiptIdempotencyKey(
        mission_id=mission_id,
        work_id=work_id,
        attempt_number=attempt_number,
        principal_id=principal_id,
    )


def dispatch_eligibility_key(receipt: "BridgeExecutionReceipt") -> ReceiptIdempotencyKey:
    return execution_receipt_key(
        receipt.mission_id, receipt.work_id, receipt.attempt_number, receipt.principal_id
    )


# ---------------------------------------------------------------------------
# APCB state machine (contract section 6)
# ---------------------------------------------------------------------------

class ExecutionReceiptStatus(StrEnum):
    """APCB-local execution state — never a terminal Aether state.

    Aether transitions (READY -> CLAIMED -> DISPATCHED -> RUNNING -> REVIEW ->
    COMPLETED, plus RUNNING -> BLOCKED/FAILED) are performed only by Aether
    services. APCB records its own observation-level state.
    """

    DISCOVERED = "discovered"
    CLAIM_REQUESTED = "claim_requested"
    CLAIMED = "claimed"
    HERDR_ATTACHED = "herdr_attached"
    PROMPTED = "prompted"
    OBSERVING = "observing"
    RECONCILING = "reconciling"
    TERMINAL = "terminal"


# ---------------------------------------------------------------------------
# Bridge execution receipt (contract sections 5, 14, 17)
# ---------------------------------------------------------------------------

@dataclass
class BridgeExecutionReceipt:
    """Persisted APCB receipt keyed by the idempotency tuple.

    Must be written BEFORE asking Herdr to start work, and consulted on every
    poll/restart/reconnect before dispatching again (contract section 5).
    """

    work_id: str
    attempt_number: int
    principal_id: str
    mission_id: str
    state: ExecutionReceiptStatus = ExecutionReceiptStatus.DISCOVERED
    herdr_execution_ref: str | None = None
    herdr_workspace_ref: str | None = None
    correlation_id: str = field(default_factory=lambda: new_id("apcb"))
    bridge_request_id: str = field(default_factory=lambda: new_id("apcb"))
    observed_at: str | None = None
    terminal_outcome: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def idempotency_key(self) -> ReceiptIdempotencyKey:
        return execution_receipt_key(
            self.mission_id, self.work_id, self.attempt_number, self.principal_id
        )

    def is_terminal(self) -> bool:
        return self.state == ExecutionReceiptStatus.TERMINAL


# ---------------------------------------------------------------------------
# Dispatch eligibility (contract section 4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DispatchEligibility:
    """All-or-nothing dispatch gate.

    A work item is dispatchable only when every field is True (contract
    section 4). APCB must never promote a blocked or approval-waiting step.
    """

    authorized: bool = False
    execution_ready: bool = False
    principal_assigned: bool = False
    profile_enabled: bool = False
    capability_match: bool = False
    workspace_bound: bool = False
    no_active_attempt: bool = False
    not_awaiting_approval: bool = False

    def __bool__(self) -> bool:
        return all(
            [
                self.authorized,
                self.execution_ready,
                self.principal_assigned,
                self.profile_enabled,
                self.capability_match,
                self.workspace_bound,
                self.no_active_attempt,
                self.not_awaiting_approval,
            ]
        )

    def blockers(self) -> list[str]:
        return [name for name, value in self.__dict__.items() if not value]


# ---------------------------------------------------------------------------
# Prompt envelope (contract section 9)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromptEnvelope:
    """Task prompt built ONLY from canonical Aether artifacts.

    APCB never forwards another principal's full transcript (section 9/10).
    """

    protocol: str = "aether.apcb.task.v1"
    work_id: str = ""
    mission_id: str = ""
    principal_id: str = ""
    attempt: int = 1
    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    relevant_decisions: list[str] = field(default_factory=list)
    relevant_artifacts: list[str] = field(default_factory=list)
    relevant_evidence: list[str] = field(default_factory=list)
    workspace_id: str = ""
    correlation_id: str = field(default_factory=lambda: new_id("apcb"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "work_id": self.work_id,
            "mission_id": self.mission_id,
            "principal_id": self.principal_id,
            "attempt": self.attempt,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "relevant_decisions": list(self.relevant_decisions),
            "relevant_artifacts": list(self.relevant_artifacts),
            "relevant_evidence": list(self.relevant_evidence),
            "workspace_id": self.workspace_id,
            "correlation_id": self.correlation_id,
        }


# ---------------------------------------------------------------------------
# Principal handoff artifact (contract section 10)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PrincipalHandoff:
    """Aether-owned handoff artifact. NOT a Herdr message.

    The handoff path is always: principal -> artifact/decision/evidence ->
    Aether canonical state -> new work item -> APCB -> Herdr -> next principal.
    """

    type: str = "principal_handoff"
    from_principal: str = ""
    to_principal: str = ""
    work_id: str = ""
    mission_id: str = ""
    summary: str = ""
    decisions: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    correlation_id: str = field(default_factory=lambda: new_id("apcb"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "from_principal": self.from_principal,
            "to_principal": self.to_principal,
            "work_id": self.work_id,
            "mission_id": self.mission_id,
            "summary": self.summary,
            "decisions": list(self.decisions),
            "artifacts": list(self.artifacts),
            "verification": list(self.verification),
            "open_questions": list(self.open_questions),
            "blockers": list(self.blockers),
            "correlation_id": self.correlation_id,
        }


# ---------------------------------------------------------------------------
# Service identity (contract section 13)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class APCBServiceIdentity:
    """APCB authenticates to Aether as a dedicated service identity.

    Distinct from AETHER_MCP_TOKEN / AETHER_MCP_OPERATOR_TOKEN / principal_id /
    Herdr credentials / provider keys. Grants only the Aether service calls
    required to coordinate work; never a mutation superuser.
    """

    name: str = "principal-coordination-bridge"
    principal_id: str = "principal-coordination-bridge"
    service: str = "apcb.v0.1"
