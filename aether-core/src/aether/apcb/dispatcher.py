"""APCB dispatcher — deterministic orchestration: eligibility -> receipt ->
conformance -> dispatch -> observe -> reconcile -> observation-level terminal.

Contract reference: project-docs/architecture/APCB_V0_1_IMPLEMENTATION_CONTRACT.md
Sections 4, 5, 6, 11. Invariants (ADR-0055 / contract):

  - Aether remains canonical state + authority. APCB never invents a terminal
    Aether state; it records observation-level terminal outcomes and lets the
    Aether service perform the authoritative transition.
  - The receipt idempotency tuple (work_id, attempt_number, principal_id) is
    persisted BEFORE dispatch and consulted on every restart/reconnect.
  - No forced fallback when the conformance gate rejects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from aether.apcb.conformance import AdapterConformance, ConformanceGate
from aether.apcb.contracts import (
    BridgeExecutionReceipt,
    DispatchEligibility,
    ExecutionReceiptStatus,
    PromptEnvelope,
    execution_receipt_key,
)
from aether.apcb.eligibility import EligibilityEvaluator, WorkItemView
from aether.apcb.herdr_adapter import AgentObservation, HerdrExecutionAdapter
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.apcb.receipt_store import ReceiptStore

LOG = logging.getLogger("aether.apcb.dispatcher")


@dataclass(frozen=True)
class DispatchDecision:
    """Result of a dispatch or reconcile attempt (observation-level)."""

    work_id: str
    mission_id: str
    principal_id: str
    attempt_number: int
    dispatched: bool = False
    status: str = "rejected"  # rejected|dispatched|resumed|promoted|failed|terminal
    eligibility: DispatchEligibility | None = None
    conformance: AdapterConformance | None = None
    receipt: BridgeExecutionReceipt | None = None
    terminal_outcome: str | None = None
    diagnostic: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_id": self.work_id,
            "mission_id": self.mission_id,
            "principal_id": self.principal_id,
            "attempt_number": self.attempt_number,
            "dispatched": self.dispatched,
            "status": self.status,
            "eligibility": {
                "eligible": bool(self.eligibility),
                "blockers": self.eligibility.blockers() if self.eligibility else [],
            }
            if self.eligibility
            else None,
            "conformance": self.conformance.summary() if self.conformance else None,
            "receipt_state": self.receipt.state.value if self.receipt else None,
            "terminal_outcome": self.terminal_outcome,
            "diagnostic": list(self.diagnostic),
        }


AetherStateObserver = Callable[[str], str]  # mission_id -> canonical state string


class APCBDispatcher:
    """Orchestrate one work item through eligibility -> dispatch -> reconcile.

    `aether_state_observer` is injected by the Aether service (Slice C). When
    omitted, the dispatcher treats mission state as "unknown" and never
    invents terminal Aether state on its own.
    """

    def __init__(
        self,
        profiles: PrincipalRuntimeProfiles,
        receipts: ReceiptStore,
        conformance_gate: ConformanceGate,
        adapter: HerdrExecutionAdapter,
        eligibility_evaluator: EligibilityEvaluator | None = None,
        aether_state_observer: AetherStateObserver | None = None,
        prompt_factory: Callable[[WorkItemView, int], PromptEnvelope] | None = None,
        workspace_verify: Callable[[str], bool] | None = None,
        wait_timeout_seconds: float = 300.0,
    ) -> None:
        self.profiles = profiles
        self.receipts = receipts
        self.conformance_gate = conformance_gate
        self.adapter = adapter
        self.eligibility = eligibility_evaluator or EligibilityEvaluator(profiles, receipts)
        self.aether_state_observer = aether_state_observer or (lambda mission_id: "unknown")
        self.prompt_factory = prompt_factory or _default_prompt_factory
        self.workspace_verify = workspace_verify
        self.wait_timeout_seconds = wait_timeout_seconds

    # ------------------------------------------------------------------ #
    # Dispatch                                                           #
    # ------------------------------------------------------------------ #
    def dispatch(self, work: WorkItemView) -> DispatchDecision:
        """All-or-nothing eligibility -> receipt -> conformance -> dispatch.

        Never dispatches when eligibility or conformance fails. Persists the
        receipt (CLAIMED) BEFORE asking Herdr to start work (contract §5).
        """
        key = execution_receipt_key(work.work_id, work.attempt_number, work.principal_id)

        existing = self.receipts.get(key)
        if existing is not None:
            # Contract section 5/11: a second poll, APCB restart, or Herdr
            # reconnect must reconcile the existing receipt before dispatching
            # again — never silently re-dispatch an owned work item.
            return self.reconcile(work, existing)

        profile_name = work.execution_profile
        if not profile_name:
            # ChatGPT hardening directive (2026-08-13): APCB must never select
            # an execution profile implicitly; the canonical work item decides.
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                diagnostic=(
                    "work item must specify execution_profile explicitly; "
                    "APCB never guesses a principal profile",
                ),
            )

        eligibility = self.eligibility.evaluate(work)
        if not eligibility:
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                eligibility=eligibility,
                diagnostic=tuple(f"eligibility:{b}" for b in eligibility.blockers()),
            )

        conformance = self.conformance_gate.evaluate(work.principal_id, profile_name)
        if not conformance.eligible:
            # No forced fallback: record the rejection durably, never dispatch.
            rejected = self.receipts.persist(
                BridgeExecutionReceipt(
                    work_id=work.work_id,
                    attempt_number=work.attempt_number,
                    principal_id=work.principal_id,
                    mission_id=work.mission_id,
                    state=ExecutionReceiptStatus.TERMINAL,
                    terminal_outcome="rejected",
                    error="; ".join(conformance.diagnostic),
                )
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                eligibility=eligibility,
                conformance=conformance,
                receipt=rejected,
                terminal_outcome="rejected",
                diagnostic=conformance.diagnostic,
            )

        if self.workspace_verify is not None and not self.workspace_verify(work.workspace_id):
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                eligibility=eligibility,
                conformance=conformance,
                diagnostic=("workspace binding failed validation",),
            )

        # Persist receipt BEFORE dispatch (contract §5 durable identity).
        receipt = self.receipts.persist(
            BridgeExecutionReceipt(
                work_id=work.work_id,
                attempt_number=work.attempt_number,
                principal_id=work.principal_id,
                mission_id=work.mission_id,
                state=ExecutionReceiptStatus.CLAIMED,
                herdr_workspace_ref=work.workspace_id or None,
            )
        )

        try:
            agent_kind = None
            ep = self.profiles.get_execution_profile(profile_name)
            if ep is not None:
                agent_kind = ep.herdr_agent_kind
            agent_ref = self.adapter.ensure_agent(work.workspace_id, work.principal_id, herdr_agent_kind=agent_kind)
            receipt = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.HERDR_ATTACHED,
                herdr_execution_ref=agent_ref,
            )

            envelope = self.prompt_factory(work, work.attempt_number)
            prompt_text = _render_prompt(envelope)
            self.adapter.prompt_agent(agent_ref, prompt_text)
            receipt = self.receipts.update(
                receipt, state=ExecutionReceiptStatus.PROMPTED
            )

            observation = self.adapter.wait_agent(
                agent_ref, self.wait_timeout_seconds
            )
            output = self.adapter.read_agent(agent_ref, limit_bytes=8192)

            terminal_outcome = self._outcome_from_observation(observation)
            receipt = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome=terminal_outcome,
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=True,
                status="dispatched",
                eligibility=eligibility,
                conformance=conformance,
                receipt=receipt,
                terminal_outcome=terminal_outcome,
                diagnostic=(),
                metadata={
                    "agent_ref": agent_ref,
                    "observation_status": observation.status,
                    "output_tail": output[-500:],
                },
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception(f"[{work.work_id}] dispatch failed")
            receipt = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome="failed",
                error=f"{type(exc).__name__}: {exc}"[:500],
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="failed",
                eligibility=eligibility,
                conformance=conformance,
                receipt=receipt,
                terminal_outcome="failed",
                diagnostic=(f"{type(exc).__name__}: {exc}",),
            )

    # ------------------------------------------------------------------ #
    # Reconcile (contract §11)                                            #
    # ------------------------------------------------------------------ #
    def reconcile(
        self,
        work: WorkItemView,
        existing: BridgeExecutionReceipt | None = None,
    ) -> DispatchDecision:
        """Reconcile before retry/dispatch: load receipt -> query Herdr ->
        inspect Aether mission state -> resume/promote/fail, never duplicate.

        Order (contract §11):
          1. Load APCB receipt by (work_id, attempt, principal_id)
          2. Query Herdr execution state
          3. Inspect Aether mission state
          4. If Aether is terminal -> stop
          5. If Herdr still running -> resume observation
          6. If Herdr complete but Aether non-terminal -> promote result
          7. If Herdr gone and Aether non-terminal -> failure evidence
          8. Only then consider retry with incremented attempt (caller decides)
        """
        receipt = existing or self.receipts.get_by_components(
            work.work_id, work.attempt_number, work.principal_id
        )
        if receipt is None:
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                diagnostic=("no receipt for tuple; reconcile before first dispatch not applicable",),
            )

        mission_state = self.aether_state_observer(work.mission_id)
        if mission_state in ("terminal", "completed", "failed", "cancelled", "blocked"):
            stopped = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome="stopped",
                error=f"aether mission terminal ({mission_state})",
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="terminal",
                receipt=stopped,
                terminal_outcome="stopped",
                diagnostic=(f"aether mission state={mission_state}",),
            )

        if not receipt.herdr_execution_ref:
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="rejected",
                receipt=receipt,
                diagnostic=("receipt has no herdr_execution_ref; nothing was dispatched",),
            )

        observation = self.adapter.observe_agent(receipt.herdr_execution_ref)
        if observation.status == "missing":
            failed = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.TERMINAL,
                terminal_outcome="failed",
                error="herdr agent gone during reconcile",
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="failed",
                receipt=failed,
                terminal_outcome="failed",
                diagnostic=("herdr agent missing during reconcile",),
            )

        if not observation.is_terminal:
            resumed = self.receipts.update(
                receipt,
                state=ExecutionReceiptStatus.RECONCILING,
                terminal_outcome=None,
            )
            return DispatchDecision(
                work_id=work.work_id,
                mission_id=work.mission_id,
                principal_id=work.principal_id,
                attempt_number=work.attempt_number,
                dispatched=False,
                status="resumed",
                receipt=resumed,
                diagnostic=(f"herdr still running (status={observation.status}); resuming observation",),
            )

        # Herdr complete, Aether non-terminal -> promote result through Aether
        # (observation-level: APCB marks its own terminal; Aether performs the
        # authoritative transition via its service in Slice C).
        outcome = self._outcome_from_observation(observation)
        promoted = self.receipts.update(
            receipt,
            state=ExecutionReceiptStatus.TERMINAL,
            terminal_outcome=outcome,
            herdr_execution_ref=receipt.herdr_execution_ref,
        )
        return DispatchDecision(
            work_id=work.work_id,
            mission_id=work.mission_id,
            principal_id=work.principal_id,
            attempt_number=work.attempt_number,
            dispatched=False,
            status="promoted",
            receipt=promoted,
            terminal_outcome=outcome,
            diagnostic=(f"herdr complete (status={observation.status}); result ready to promote",),
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _outcome_from_observation(observation: AgentObservation) -> str:
        if observation.status == "done":
            return "completed"
        if observation.status in ("blocked", "terminated"):
            return "blocked"
        if observation.error:
            return "failed"
        return "unknown"


def _default_prompt_factory(work: WorkItemView, attempt: int) -> PromptEnvelope:
    return PromptEnvelope(
        work_id=work.work_id,
        mission_id=work.mission_id,
        principal_id=work.principal_id,
        attempt=attempt,
        objective=str(work.metadata.get("objective") or ""),
        constraints=list(work.metadata.get("constraints") or []),
        acceptance_criteria=list(work.metadata.get("acceptance_criteria") or []),
        relevant_decisions=list(work.metadata.get("relevant_decisions") or []),
        relevant_artifacts=list(work.metadata.get("relevant_artifacts") or []),
        relevant_evidence=list(work.metadata.get("relevant_evidence") or []),
        workspace_id=work.workspace_id,
    )


def _render_prompt(envelope: PromptEnvelope) -> str:
    """Render the canonical envelope as the prompt handed to the worker.

    Only canonical Aether artifacts are forwarded — never another principal's
    full transcript (contract §9/§10).
    """
    parts = [f"protocol: {envelope.protocol}", f"work_id: {envelope.work_id}"]
    if envelope.mission_id:
        parts.append(f"mission_id: {envelope.mission_id}")
    parts.append(f"principal_id: {envelope.principal_id}")
    parts.append(f"attempt: {envelope.attempt}")
    if envelope.workspace_id:
        parts.append(f"workspace_id: {envelope.workspace_id}")
    if envelope.correlation_id:
        parts.append(f"correlation_id: {envelope.correlation_id}")
    if envelope.objective:
        parts.append(f"objective: {envelope.objective}")
    if envelope.constraints:
        parts.append("constraints:\n- " + "\n- ".join(envelope.constraints))
    if envelope.acceptance_criteria:
        parts.append("acceptance_criteria:\n- " + "\n- ".join(envelope.acceptance_criteria))
    if envelope.relevant_decisions:
        parts.append("relevant_decisions: " + ", ".join(envelope.relevant_decisions))
    if envelope.relevant_artifacts:
        parts.append("relevant_artifacts: " + ", ".join(envelope.relevant_artifacts))
    if envelope.relevant_evidence:
        parts.append("relevant_evidence: " + ", ".join(envelope.relevant_evidence))
    return "\n".join(parts)
