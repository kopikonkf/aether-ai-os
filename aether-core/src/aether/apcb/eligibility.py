"""APCB dispatch eligibility — all-or-nothing gate (contract section 4).

A work item is dispatchable only when ALL of these are true:

  1. authorized              -> mission/step already authorized by Aether policy
  2. execution_ready         -> step is in an execution-ready state
  3. principal_assigned      -> principal_id explicitly assigned
  4. profile_enabled         -> principal execution profile is enabled
  5. capability_match        -> required capabilities match the principal profile
  6. workspace_bound         -> a valid workspace binding exists
  7. no_active_attempt       -> no active APCB attempt owns the work item
  8. not_awaiting_approval   -> the work item is not awaiting human approval

APCB must never promote a blocked or approval-waiting step into Herdr
execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from aether.apcb.contracts import DispatchEligibility
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.apcb.receipt_store import ReceiptStore


@dataclass(frozen=True)
class WorkItemView:
    """The canonical work-item fields APCB reads to judge eligibility.

    APCB reads only what Aether owns; it never fabricates policy fields.
    `execution_profile` is the explicit herdr:* profile the canonical work item
    assigns to this principal. APCB never guesses a profile implicitly.
    """

    work_id: str
    mission_id: str
    principal_id: str
    required_capabilities: tuple[str, ...] = ()
    workspace_id: str = ""
    authorized: bool = False
    execution_ready: bool = False
    awaiting_approval: bool = False
    attempt_number: int = 1
    execution_profile: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class EligibilityEvaluator:
    """Build a DispatchEligibility from a work item + registry + receipt store.

    Each of the eight contract conditions maps to exactly one boolean; the
    result's `blockers()` names every condition that failed.

    `profile_enabled` is strict: the work item must name an execution profile
    and that profile must be assigned to the principal. An empty
    execution_profile fails eligibility — APCB never selects a profile on the
    principal's behalf (ChatGPT hardening directive, 2026-08-13).
    """

    def __init__(
        self,
        profiles: PrincipalRuntimeProfiles,
        receipts: ReceiptStore,
    ) -> None:
        self.profiles = profiles
        self.receipts = receipts

    def evaluate(self, work: WorkItemView) -> DispatchEligibility:
        principal = self.profiles.get_principal(work.principal_id)
        profile_enabled = False
        capability_match = False
        if principal is not None:
            profile_enabled = (
                bool(work.execution_profile)
                and work.execution_profile in principal.execution_profiles
            )
            capability_match = all(
                principal.has_capability(cap) for cap in work.required_capabilities
            ) if work.required_capabilities else True

        return DispatchEligibility(
            authorized=bool(work.authorized),
            execution_ready=bool(work.execution_ready),
            principal_assigned=bool(work.principal_id),
            profile_enabled=profile_enabled,
            capability_match=capability_match,
            workspace_bound=bool(work.workspace_id),
            no_active_attempt=not self.receipts.has_active_attempt(
                work.work_id, work.principal_id
            ),
            not_awaiting_approval=not bool(work.awaiting_approval),
        )

    def evaluate_dict(self, work: Mapping[str, Any]) -> DispatchEligibility:
        view = WorkItemView(
            work_id=str(work.get("work_id") or work.get("work_item_id") or ""),
            mission_id=str(work.get("mission_id") or ""),
            principal_id=str(work.get("principal_id") or work.get("agent") or ""),
            required_capabilities=tuple(work.get("required_capabilities") or ()),
            workspace_id=str(work.get("workspace_id") or ""),
            authorized=bool(work.get("authorized") or work.get("execution_authorized")),
            execution_ready=bool(work.get("execution_ready")),
            awaiting_approval=bool(work.get("awaiting_approval") or work.get("pending_approval")),
            attempt_number=int(work.get("attempt_number") or 1),
            execution_profile=str(work.get("execution_profile") or ""),
            metadata=dict(work.get("metadata") or {}),
        )
        return self.evaluate(view)
