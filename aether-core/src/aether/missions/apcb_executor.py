"""APCB mission action executor — Slice C scaffold (MISSION-PCP-001).

Wires the mission action boundary (aether.contracts.missions.MissionActionExecutor)
to APCB so mission steps are executed deterministically by a principal via the
Principal Coordination Bridge (dispatch -> reconcile -> artifact authority)
instead of a pure local executor.

Division of responsibility (Founder directive, 2026-08-13):
  - MissionOrchestrator REMAINS the owner of mission semantics: plan, steps,
    retry/budget, approval checkpoints, outcome.
  - APCB is ONLY the deterministic execution coordinator: eligibility ->
    receipt -> conformance -> dispatch -> observe -> reconcile, and the
    artifact-acceptance authority.

Design notes for the caller:
  - work_mapper(action, attempt) -> WorkItemView maps an ActionProposal onto a
    canonical APCB work item. When a custom work_mapper is not supplied, the
    executor uses the canonical governed mapper
    (build_canonical_work_mapper) which derives principal_id,
    execution_profile, workspace_id and capabilities from the mission step
    action metadata + the Aether principal profile registry — fail-closed
    when nothing is assigned (see canonical_mapper.py). The attempt number is
    read from proposal.metadata["mission_attempt_number"] (default 1), so
    retries are reflected in the APCB receipt and keep idempotency. Example:
    one mission step -> one work item on the principal's execution profile and
    pane-bound workspace.
  - dispatcher.dispatch(work) is SYNCHRONOUS. A live Herdr adapter can block
    until the pane finishes; callers that cannot afford a blocking await should
    run the mission loop in an executor thread.
  - APCB never creates approvals. awaiting_approval work is passed through as a
    pending-approval ActionResult so MissionGovernor / TrustedApprovalInbox
    remains the single approval authority. approval_result() always returns
    None for the same reason.
"""
from __future__ import annotations

from typing import Any, Callable

from aether.apcb.dispatcher import APCBDispatcher, DispatchDecision
from aether.apcb.eligibility import WorkItemView
from aether.apcb.profiles import PrincipalRuntimeProfiles
from aether.contracts.actions import ActionProposal, ActionResult

from .canonical_mapper import MISSION_ATTEMPT_NUMBER, build_canonical_work_mapper

MISSION_ATTEMPT_METADATA_KEY = MISSION_ATTEMPT_NUMBER


def _normalize_attempt(value: Any) -> int:
    """Coerce a metadata value into a positive attempt number; invalid -> 1."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 1
    return number if number >= 1 else 1


def _attempt_from_proposal(proposal: ActionProposal) -> int:
    raw = (proposal.metadata or {}).get(MISSION_ATTEMPT_METADATA_KEY)
    return _normalize_attempt(raw)


class ApcbMissionActionExecutor:
    """MissionActionExecutor that runs each step through an APCB dispatcher.

    `dispatcher` may be a live APCBDispatcher instance or a zero-argument
    factory Callable that returns one (so callers can lazily construct the real
    profile registry + receipt store + herdr adapter wiring).

    `work_mapper` is optional. When omitted, a canonical governed mapper built
    from `profiles` is used (build_canonical_work_mapper), deriving the work
    item from mission action metadata + the principal profile registry. When
    both are omitted the executor fails closed (ValueError) — APCB never runs a
    step without a governed principal/profile derivation.

    `mission_state_observer` is an optional exposure for the live runner: the
    canonical Aether mission-state observer (aether.missions.mission_state_observer)
    so the dispatcher honours LIVE mission terminal state during dispatch/
    reconcile (F-07). The dispatcher itself must be constructed with the
    observer — this executor merely carries it for callers that build the
    dispatcher inside a factory.
    """

    def __init__(
        self,
        dispatcher: APCBDispatcher | Callable[[], APCBDispatcher],
        work_mapper: Callable[[ActionProposal, int], WorkItemView] | None = None,
        *,
        profiles: PrincipalRuntimeProfiles | None = None,
        mission_state_observer: Callable[[str], str] | None = None,
    ) -> None:
        self._dispatcher_factory: Callable[[], APCBDispatcher] = (
            dispatcher if callable(dispatcher) else (lambda: dispatcher)
        )
        if work_mapper is None:
            if profiles is None:
                raise ValueError(
                    "ApcbMissionActionExecutor requires either a custom work_mapper "
                    "or a PrincipalRuntimeProfiles registry to build the canonical "
                    "governed mapper (fail-closed: APCB never guesses a principal/profile)."
                )
            work_mapper = build_canonical_work_mapper(profiles)
        self.work_mapper = work_mapper
        self.mission_state_observer = mission_state_observer

    # ------------------------------------------------------------------ #
    # MissionActionExecutor protocol                                      #
    # ------------------------------------------------------------------ #
    async def execute(self, proposal: ActionProposal) -> ActionResult:
        """Run one mission step through APCB and translate to ActionResult.

        The attempt number is read from proposal.metadata["mission_attempt_number"]
        (default 1) so every retry is reflected in the APCB work item and receipt.
        APCB never fabricates policy: awaiting_approval work is returned as a
        pending-approval ActionResult so the mission can hold at its approval
        checkpoint while MissionGovernor decides.
        """
        attempt = _attempt_from_proposal(proposal)
        work = self.work_mapper(proposal, attempt)
        if work.awaiting_approval:
            # APCB is not an approval mechanism — pass through to the governor.
            return ActionResult(
                action_id=proposal.action_id,
                ok=False,
                status="pending-approval",
                metadata={"apcb_status": "pending-approval"},
            )
        decision = self._dispatcher_factory().dispatch(work)
        return _decision_to_action_result(proposal, decision)

    async def approval_result(self, approval_id: str) -> ActionResult | None:
        """APCB does not implement approvals; always None.

        The orchestrator's approval resume path stays on
        MissionGovernor / TrustedApprovalInbox, which produces the terminal
        result via a separate, governed channel.
        """
        return None


def _decision_to_action_result(
    proposal: ActionProposal, decision: DispatchDecision
) -> ActionResult:
    """Translate an APCB DispatchDecision into an ActionResult (bounded map).

    Mapping rules (Slice C scaffold):
      - dispatched + completed                    -> ok=True, output from metadata
      - completed_without_artifact                -> ok=True + artifact_missing
      - rejected / failed / terminal              -> ok=False + diagnostic
      - dispatched + failed/unknown               -> ok=False + terminal_outcome
    """
    outcome = decision.terminal_outcome
    common_meta: dict[str, Any] = {
        **dict(decision.metadata or {}),
        "apcb_status": decision.status,
    }

    if decision.status == "dispatched" and outcome == "completed":
        return ActionResult(
            action_id=proposal.action_id,
            ok=True,
            status="completed",
            output=decision.metadata.get("output_tail"),
            metadata=common_meta,
        )

    if outcome == "completed_without_artifact":
        return ActionResult(
            action_id=proposal.action_id,
            ok=True,
            status="completed_without_artifact",
            output=decision.metadata.get("output_tail"),
            metadata={**common_meta, "artifact_missing": True},
        )

    if decision.status in ("rejected", "failed", "terminal"):
        error = "; ".join(decision.diagnostic) or outcome or decision.status
        return ActionResult(
            action_id=proposal.action_id,
            ok=False,
            status=decision.status,
            error=error,
            metadata=common_meta,
        )

    if decision.status == "dispatched" and outcome in ("failed", "unknown"):
        return ActionResult(
            action_id=proposal.action_id,
            ok=False,
            status=outcome or decision.status,
            error=outcome or decision.status,
            metadata=common_meta,
        )

    # Defensive fallback: unknown decision shape -> failed, observation-derived.
    return ActionResult(
        action_id=proposal.action_id,
        ok=False,
        status=decision.status,
        error="; ".join(decision.diagnostic) or decision.status,
        metadata=common_meta,
    )
