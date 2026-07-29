"""Mandate-bound reversible experiment governance and evidence accounting."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aether.contracts.experiments import (
    DemandEvidenceState, DemandSignal, DemandSignalKind, ExperimentBlocked,
    ExperimentRunReceipt, ExperimentStatus, ExperimentStepKind, ExternalActionReview,
    ExternalActionReviewState, ReversibleExperimentPlan, demand_signal_hash,
    experiment_plan_hash, experiment_run_hash,
)
from aether.contracts.opportunities import AutonomyLevel, MandateStatus
from aether.experiments.store import SQLiteExperimentStore
from aether.opportunities.store import SQLiteOpportunityStore
from aether.utils.time import utc_now


class ExperimentGovernor:
    def __init__(self, trusted_principals: tuple[str, ...] = ("founder", "operator")) -> None:
        self.trusted_principals = tuple(value.casefold() for value in trusted_principals)

    def require_trusted(self, principal: str) -> None:
        if principal.casefold() not in self.trusted_principals:
            raise ExperimentBlocked(("trusted principal required",))


class ReversibleExperimentEngine:
    def __init__(
        self, store: SQLiteExperimentStore, opportunity_store: SQLiteOpportunityStore,
        *, governor: ExperimentGovernor | None = None,
    ) -> None:
        self.store = store
        self.opportunity_store = opportunity_store
        self.governor = governor or ExperimentGovernor()

    def create_plan(self, plan: ReversibleExperimentPlan) -> ReversibleExperimentPlan:
        candidate = self.opportunity_store.get_candidate(plan.candidate_id)
        mandate = next((item for item in self.opportunity_store.mandates(plan.candidate_id) if item.mandate_id == plan.mandate_id), None)
        blockers: list[str] = []
        if mandate is None:
            blockers.append("experiment mandate not found")
        else:
            if mandate.status != MandateStatus.ACTIVE:
                blockers.append("experiment mandate is not active")
            now = datetime.now(timezone.utc)
            expires = datetime.fromisoformat(mandate.expires_at.replace("Z", "+00:00"))
            if now >= expires:
                blockers.append("experiment mandate expired")
            if mandate.autonomy_level not in {AutonomyLevel.SANDBOX_EXPERIMENT, AutonomyLevel.BOUNDED_EXTERNAL}:
                blockers.append("mandate does not grant experiment authority")
            if plan.maximum_cost_usd > mandate.maximum_cost_usd:
                blockers.append("plan cost exceeds mandate")
            if plan.maximum_duration_seconds > mandate.maximum_duration_seconds:
                blockers.append("plan duration exceeds mandate")
            total_external = sum(step.external_actions for step in plan.steps)
            if total_external > mandate.maximum_external_actions:
                blockers.append("plan external actions exceed mandate")
            allowed = set(mandate.allowed_capabilities)
            for step in plan.steps:
                if step.capability not in allowed:
                    blockers.append(f"capability not granted by mandate: {step.capability}")
                if mandate.reversible_only and not step.reversible:
                    blockers.append(f"irreversible step not allowed: {step.name}")
                if step.kind == ExperimentStepKind.EXTERNAL_ACTION and mandate.autonomy_level != AutonomyLevel.BOUNDED_EXTERNAL:
                    blockers.append("external action requires bounded-external mandate")
        if not plan.steps:
            blockers.append("experiment plan requires steps")
        if not plan.success_metrics or not plan.stop_conditions:
            blockers.append("experiment plan requires success metrics and stop conditions")
        if sum(step.estimated_cost_usd for step in plan.steps) > plan.maximum_cost_usd:
            blockers.append("step estimates exceed plan budget")
        if plan.maximum_artifact_bytes < 1024:
            blockers.append("artifact budget is too small")
        if plan.maximum_artifact_files < 1 or plan.maximum_artifact_files > 50:
            blockers.append("artifact file budget must be between 1 and 50")
        if blockers:
            raise ExperimentBlocked(tuple(dict.fromkeys(blockers)))
        stamped = replace(plan, created_at=plan.created_at or utc_now())
        stamped = replace(stamped, plan_hash=experiment_plan_hash(stamped))
        return self.store.add_plan(stamped)

    def record_run(self, item: ExperimentRunReceipt) -> ExperimentRunReceipt:
        plan = self.store.get_plan(item.plan_id)
        if item.candidate_id != plan.candidate_id or item.mandate_id != plan.mandate_id:
            raise ExperimentBlocked(("run lineage does not match plan",))
        if item.cost_usd > plan.maximum_cost_usd:
            raise ExperimentBlocked(("run cost exceeds plan budget",))
        stamped = replace(item, run_hash=experiment_run_hash(replace(item, run_hash="")))
        return self.store.add_run(stamped)

    def record_demand_signal(self, item: DemandSignal, *, principal: str | None = None) -> DemandSignal:
        self.store.get_run(item.run_id)
        blockers: list[str] = []
        if item.quantity < 0:
            blockers.append("demand quantity cannot be negative")
        if item.kind == DemandSignalKind.SYNTHETIC and item.state != DemandEvidenceState.SYNTHETIC:
            blockers.append("synthetic signals cannot be measured or verified")
        if item.state in {DemandEvidenceState.MEASURED, DemandEvidenceState.VERIFIED} and not item.external_reference:
            blockers.append("measured demand requires external reference")
        verifier = item.verifier
        if item.state == DemandEvidenceState.VERIFIED:
            if not principal:
                blockers.append("verified demand requires trusted verifier")
            else:
                self.governor.require_trusted(principal)
                verifier = principal
        if blockers:
            raise ExperimentBlocked(blockers)
        stamped = replace(item, verifier=verifier, signal_hash=demand_signal_hash(replace(item, signal_hash="")))
        return self.store.add_signal(stamped)

    def request_external_review(
        self, *, run_id: str, step_id: str, action_summary: str, consequence: str,
        requested_by: str, ttl_seconds: int = 3600,
    ) -> ExternalActionReview:
        if not run_id.strip():
            raise ExperimentBlocked(("run_id is required",))
        if ttl_seconds < 60:
            raise ExperimentBlocked(("review TTL must be at least 60 seconds",))
        now = datetime.now(timezone.utc)
        return self.store.add_review(ExternalActionReview(
            run_id=run_id, step_id=step_id, action_summary=action_summary, consequence=consequence,
            requested_by=requested_by, requested_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z"),
        ))

    def decide_external_review(
        self, review_id: str, *, approved: bool, principal: str, reason: str,
    ) -> ExternalActionReview:
        self.governor.require_trusted(principal)
        review = next((item for item in self.store.reviews(limit=1000) if item.review_id == review_id), None)
        if review is None:
            raise ExperimentBlocked(("external action review not found",))
        if review.state != ExternalActionReviewState.REQUIRED:
            raise ExperimentBlocked(("external action review already decided",))
        if datetime.now(timezone.utc) >= datetime.fromisoformat(review.expires_at.replace("Z", "+00:00")):
            state = ExternalActionReviewState.EXPIRED
        else:
            state = ExternalActionReviewState.APPROVED if approved else ExternalActionReviewState.REJECTED
        # Append a decision receipt rather than mutating the request.
        decided = replace(
            review, review_id=f"{review.review_id}:{state.value}", state=state,
            decided_by=principal, decided_at=utc_now(), reason=reason,
        )
        return self.store.add_review(decided)
