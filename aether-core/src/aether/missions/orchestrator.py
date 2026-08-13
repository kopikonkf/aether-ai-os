"""Northstar-bounded, resumable mission orchestration."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from aether.contracts.actions import ActionProposal, ActionResult
from aether.contracts.event_types import EventType
from aether.contracts.evolution import EvolutionTrigger, EvolutionTriggerType
from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.contracts.missions import (
    ExpectedValueBrief,
    MissionActionExecutor,
    MissionBlocked,
    MissionBudget,
    MissionDecision,
    MissionDecisionConflict,
    MissionDecisionType,
    MissionExecution,
    MissionLane,
    MissionOutcome,
    MissionOutcomeState,
    MissionPlan,
    MissionStatus,
    MissionStep,
    MissionStepAttempt,
    MissionStepStatus,
    MissionValueEvidence,
    MissionValueKind,
    OpportunityEvidence,
    OpportunityEvidenceStance,
    evidence_hash,
    mission_plan_hash,
    opportunity_brief_hash,
)
from aether.events import EventBus
from aether.utils.ids import new_id
from aether.utils.time import utc_now

from .governance import MissionGovernor
from .store import SQLiteMissionStore

_TERMINAL = {
    MissionStatus.REJECTED,
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.CANCELLED,
    MissionStatus.STOPPED,
}


class MissionOrchestrator:
    orchestrator_id = "aether.mission-orchestrator"

    def __init__(
        self,
        store: SQLiteMissionStore,
        action_executor: MissionActionExecutor,
        *,
        governor: MissionGovernor | None = None,
        event_bus: EventBus | None = None,
        memory_fabric: Any | None = None,
        evolution_engine: Any | None = None,
        maximum_steps_per_run: int = 5,
    ) -> None:
        self.store = store
        self.action_executor = action_executor
        self.governor = governor or MissionGovernor()
        self.event_bus = event_bus
        self.memory_fabric = memory_fabric
        self.evolution_engine = evolution_engine
        self.maximum_steps_per_run = max(1, int(maximum_steps_per_run))

    def intake_opportunity(
        self,
        *,
        title: str,
        lane: MissionLane,
        problem_statement: str,
        beneficiary: str,
        value_proposition: str,
        probability_success: float,
        upside_usd: float,
        estimated_cost_usd: float,
        estimated_duration_hours: float,
        revenue_hypothesis: str,
        assumptions: Sequence[str],
        evidence: Sequence[OpportunityEvidence],
        risk,
        confidence: float,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExpectedValueBrief:
        normalized_evidence: list[OpportunityEvidence] = []
        for item in evidence:
            normalized_evidence.append(replace(
                item,
                observed_at=item.observed_at or utc_now(),
                content_hash=item.content_hash or evidence_hash(item.source, item.statement, item.external_reference),
            ))
        supporting_sources = {
            (item.independent_source_id or item.source).strip().casefold()
            for item in normalized_evidence
            if item.stance == OpportunityEvidenceStance.SUPPORTS
            and (item.independent_source_id or item.source).strip()
        }
        contradictions = tuple(item.evidence_id for item in normalized_evidence if item.stance == OpportunityEvidenceStance.CONTRADICTS)
        expected = float(probability_success) * float(upside_usd) - float(estimated_cost_usd)
        draft = ExpectedValueBrief(
            title=title,
            lane=lane,
            problem_statement=problem_statement,
            beneficiary=beneficiary,
            value_proposition=value_proposition,
            probability_success=float(probability_success),
            upside_usd=float(upside_usd),
            estimated_cost_usd=float(estimated_cost_usd),
            estimated_duration_hours=float(estimated_duration_hours),
            expected_net_value_usd=expected,
            revenue_hypothesis=revenue_hypothesis,
            assumptions=tuple(str(item) for item in assumptions),
            evidence=tuple(normalized_evidence),
            contradiction_evidence_ids=contradictions,
            independent_support_count=len(supporting_sources),
            risk=risk,
            confidence=float(confidence),
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        blockers = self.governor.validate_brief(draft)
        brief = replace(draft, blockers=blockers)
        brief = replace(brief, brief_hash=opportunity_brief_hash(brief))
        saved = self.store.add_brief(brief)
        self._emit(EventType.MISSION_OPPORTUNITY_INTAKE, {
            "brief_id": saved.brief_id,
            "lane": saved.lane.value,
            "expected_net_value_usd": saved.expected_net_value_usd,
            "independent_support_count": saved.independent_support_count,
            "contradiction_count": len(saved.contradiction_evidence_ids),
            "blockers": list(saved.blockers),
        }, severity="warning" if saved.blockers else "info")
        return saved

    def create_plan(
        self,
        *,
        brief_id: str,
        objective: str,
        northstar_alignment: str,
        northstar_principle_ids: Sequence[str],
        strategy_tags: Sequence[str],
        steps: Sequence[MissionStep],
        budget: MissionBudget,
        stop_conditions: Sequence[str],
        metadata: Mapping[str, Any] | None = None,
    ) -> MissionPlan:
        brief = self.store.get_brief(brief_id)
        ordered_steps = tuple(replace(item, step_order=index) for index, item in enumerate(steps, start=1))
        draft = MissionPlan(
            brief_id=brief_id,
            objective=objective,
            lane=brief.lane,
            northstar_alignment=northstar_alignment,
            northstar_principle_ids=tuple(northstar_principle_ids),
            strategy_tags=tuple(strategy_tags),
            steps=ordered_steps,
            budget=budget,
            stop_conditions=tuple(stop_conditions),
            metadata=dict(metadata or {}),
            created_at=utc_now(),
        )
        blockers = self.governor.validate_plan(draft, brief)
        if blockers:
            raise MissionBlocked(blockers)
        plan = replace(draft, plan_hash=mission_plan_hash(draft))
        saved = self.store.add_plan(plan)
        self.store.transition(saved.mission_id, MissionStatus.REVIEW_REQUIRED, principal=self.orchestrator_id, reason="mission plan requires trusted review")
        self._emit(EventType.MISSION_PLAN_PROPOSED, {
            "mission_id": saved.mission_id,
            "brief_id": saved.brief_id,
            "lane": saved.lane.value,
            "plan_hash": saved.plan_hash,
            "step_count": len(saved.steps),
            "max_cost_usd": saved.budget.max_cost_usd,
        })
        return saved

    def decide(self, mission_id: str, *, approved: bool, principal: str, channel: str, reason: str) -> MissionDecision:
        blockers = self.governor.validate_decision(principal=principal, reason=reason)
        if blockers:
            raise MissionBlocked(blockers)
        existing = self.store.get_decision(mission_id)
        requested = MissionDecisionType.APPROVE if approved else MissionDecisionType.REJECT
        if existing is not None:
            if existing.decision != requested:
                raise MissionDecisionConflict(f"mission already has terminal decision {existing.decision.value}")
            return existing
        decision = self.store.add_decision(MissionDecision(
            mission_id=mission_id,
            decision=requested,
            principal=principal,
            channel=channel,
            reason=reason,
            decided_at=utc_now(),
        ))
        status = MissionStatus.APPROVED if approved else MissionStatus.REJECTED
        self.store.transition(mission_id, status, principal=principal, reason=reason, metadata={"decision_id": decision.decision_id})
        self._emit(EventType.MISSION_APPROVED if approved else EventType.MISSION_REJECTED, {
            "mission_id": mission_id,
            "decision_id": decision.decision_id,
            "principal": principal,
            "reason": reason,
        }, severity="info" if approved else "warning")
        return decision

    async def run(self, mission_id: str, *, principal: str = "aether.mission-orchestrator", maximum_steps: int | None = None) -> MissionExecution:
        plan = self.store.get_plan(mission_id)
        status = self.store.current_status(mission_id)
        if status in _TERMINAL:
            return self._execution(plan, blockers=(f"mission is terminal: {status.value}",))
        if status in {MissionStatus.DRAFT, MissionStatus.REVIEW_REQUIRED}:
            raise MissionBlocked(("mission requires trusted approval before execution",))
        if status == MissionStatus.PAUSED:
            self.store.transition(mission_id, MissionStatus.RUNNING, principal=principal, reason="mission resumed")
            self._emit(EventType.MISSION_RESUMED, {"mission_id": mission_id, "principal": principal})
        elif status == MissionStatus.APPROVED:
            self.store.transition(mission_id, MissionStatus.RUNNING, principal=principal, reason="mission execution started")
            self._emit(EventType.MISSION_STARTED, {"mission_id": mission_id, "lane": plan.lane.value})

        if self.store.current_status(mission_id) == MissionStatus.WAITING_APPROVAL:
            resumed = await self._resume_waiting_approval(plan, principal=principal)
            if resumed is not None:
                return resumed

        budget_blockers = self._budget_blockers(plan)
        if budget_blockers:
            return self._stop(plan, budget_blockers, principal=principal)

        limit = max(1, min(int(maximum_steps or self.maximum_steps_per_run), self.maximum_steps_per_run))
        completed_this_run = 0
        while completed_this_run < limit:
            completed = self._completed_step_ids(plan)
            if len(completed) == len(plan.steps):
                self.store.transition(mission_id, MissionStatus.COMPLETED, principal=principal, reason="all mission steps completed")
                self._emit(EventType.MISSION_COMPLETED, {"mission_id": mission_id, "completed_step_ids": sorted(completed)})
                return self._execution(plan)
            budget_blockers = self._budget_blockers(plan)
            if budget_blockers:
                return self._stop(plan, budget_blockers, principal=principal)
            step = self._next_step(plan, completed)
            if step is None:
                return self._stop(plan, ("no executable step remains; dependency graph is blocked",), principal=principal)
            latest = self.store.latest_attempt(mission_id, step.step_id)
            attempt_number = self._next_attempt_number(mission_id, step.step_id)
            if latest and latest.status == MissionStepStatus.FAILED:
                if attempt_number > step.max_attempts:
                    return await self._fail(plan, step, latest.error or "step exhausted retry budget", latest.failure_fingerprint, principal)
                if not (step.explicit_retry_reason or "").strip():
                    self.store.transition(mission_id, MissionStatus.PAUSED, principal=principal, reason="failed step requires explicit retry reason", metadata={"step_id": step.step_id})
                    self._emit(EventType.MISSION_PAUSED, {"mission_id": mission_id, "step_id": step.step_id, "reason": "explicit retry reason required"}, severity="warning")
                    return self._execution(plan, current_step_id=step.step_id, blockers=("explicit retry reason required before repeating failed step",))

            action = replace(step.action,
                retry_reason=step.explicit_retry_reason if latest and latest.status == MissionStepStatus.FAILED else step.action.retry_reason,
                metadata={**dict(step.action.metadata), "mission_id": mission_id, "mission_step_id": step.step_id, "mission_lane": plan.lane.value,
                          "estimated_cost_usd": step.estimated_cost_usd, "success_criteria": list(step.success_criteria),
                          "mission_attempt_number": attempt_number},
            )
            started_at = utc_now()
            self._emit(EventType.MISSION_STEP_STARTED, {
                "mission_id": mission_id, "step_id": step.step_id, "step_order": step.step_order,
                "attempt_number": attempt_number, "action_id": action.action_id,
            })
            result = await self.action_executor.execute(action)
            if result.status == "pending-approval":
                approval_id = str(result.metadata.get("approval_id") or "")
                self.store.add_attempt(MissionStepAttempt(
                    mission_id=mission_id, step_id=step.step_id, attempt_number=attempt_number,
                    status=MissionStepStatus.WAITING_APPROVAL, action_id=action.action_id,
                    approval_id=approval_id or None, estimated_cost_usd=step.estimated_cost_usd,
                    metadata={"action_status": result.status}, started_at=started_at,
                ))
                self.store.transition(mission_id, MissionStatus.WAITING_APPROVAL, principal=principal, reason="mission step requires trusted action approval", metadata={"step_id": step.step_id, "approval_id": approval_id})
                self._emit(EventType.MISSION_STEP_WAITING_APPROVAL, {"mission_id": mission_id, "step_id": step.step_id, "approval_id": approval_id}, severity="warning")
                return self._execution(plan, current_step_id=step.step_id, approval_id=approval_id)
            completed_at = utc_now()
            if result.ok:
                self.store.add_attempt(MissionStepAttempt(
                    mission_id=mission_id, step_id=step.step_id, attempt_number=attempt_number,
                    status=MissionStepStatus.COMPLETED, action_id=action.action_id, output=result.output,
                    estimated_cost_usd=step.estimated_cost_usd, metadata={**dict(result.metadata), "action_status": result.status},
                    started_at=started_at, completed_at=completed_at,
                ))
                self._emit(EventType.MISSION_STEP_COMPLETED, {"mission_id": mission_id, "step_id": step.step_id, "attempt_number": attempt_number, "action_id": action.action_id})
                completed_this_run += 1
                continue
            failed = self.store.add_attempt(MissionStepAttempt(
                mission_id=mission_id, step_id=step.step_id, attempt_number=attempt_number,
                status=MissionStepStatus.FAILED, action_id=action.action_id, error=result.error,
                failure_fingerprint=result.failure_fingerprint, estimated_cost_usd=step.estimated_cost_usd,
                metadata={**dict(result.metadata), "action_status": result.status}, started_at=started_at, completed_at=completed_at,
            ))
            self._emit(EventType.MISSION_STEP_FAILED, {"mission_id": mission_id, "step_id": step.step_id, "attempt_number": attempt_number,
                "failure_fingerprint": result.failure_fingerprint, "error": result.error}, severity="error")
            if step.stop_on_failure or attempt_number >= step.max_attempts:
                return await self._fail(plan, step, result.error or "mission step failed", result.failure_fingerprint, principal)
            completed_this_run += 1

        completed = self._completed_step_ids(plan)
        if len(completed) == len(plan.steps):
            self.store.transition(mission_id, MissionStatus.COMPLETED, principal=principal, reason="all mission steps completed")
            self._emit(EventType.MISSION_COMPLETED, {"mission_id": mission_id, "completed_step_ids": sorted(completed)})
            return self._execution(plan)
        self.store.transition(mission_id, MissionStatus.PAUSED, principal=principal, reason="bounded continuation checkpoint", metadata={"maximum_steps_per_run": limit})
        self._emit(EventType.MISSION_PAUSED, {"mission_id": mission_id, "reason": "bounded continuation checkpoint", "completed_this_run": completed_this_run})
        return self._execution(plan, blockers=("bounded continuation checkpoint reached",), metadata={"continuation_allowed": True})

    async def _resume_waiting_approval(self, plan: MissionPlan, *, principal: str) -> MissionExecution | None:
        waiting = [item for item in self.store.attempts(plan.mission_id) if item.status == MissionStepStatus.WAITING_APPROVAL]
        if not waiting:
            self.store.transition(plan.mission_id, MissionStatus.PAUSED, principal=principal, reason="approval checkpoint missing")
            return self._execution(plan, blockers=("approval checkpoint missing",))
        item = waiting[-1]
        if not item.approval_id:
            return self._execution(plan, current_step_id=item.step_id, blockers=("approval id missing from checkpoint",))
        result = await self.action_executor.approval_result(item.approval_id)
        if result is None:
            return self._execution(plan, current_step_id=item.step_id, approval_id=item.approval_id)
        step = next(step for step in plan.steps if step.step_id == item.step_id)
        if result.ok:
            self.store.add_attempt(replace(item,
                attempt_id=new_id("mission-attempt"), status=MissionStepStatus.COMPLETED,
                output=result.output, error=None, failure_fingerprint=None,
                metadata={**dict(item.metadata), **dict(result.metadata), "resumed_from_approval": item.approval_id},
                completed_at=utc_now(),
            ))
            self.store.transition(plan.mission_id, MissionStatus.RUNNING, principal=principal, reason="approved mission step resumed", metadata={"approval_id": item.approval_id, "step_id": item.step_id})
            self._emit(EventType.MISSION_RESUMED, {"mission_id": plan.mission_id, "step_id": item.step_id, "approval_id": item.approval_id})
            self._emit(EventType.MISSION_STEP_COMPLETED, {"mission_id": plan.mission_id, "step_id": item.step_id, "approval_id": item.approval_id})
            return None
        failed = replace(item,
            attempt_id=new_id("mission-attempt"), status=MissionStepStatus.FAILED,
            error=result.error or result.status, failure_fingerprint=result.failure_fingerprint,
            metadata={**dict(item.metadata), **dict(result.metadata), "resumed_from_approval": item.approval_id}, completed_at=utc_now(),
        )
        self.store.add_attempt(failed)
        return await self._fail(plan, step, failed.error or "approved action failed", failed.failure_fingerprint, principal)

    def pause(self, mission_id: str, *, principal: str, reason: str) -> MissionExecution:
        status = self.store.current_status(mission_id)
        if status in _TERMINAL:
            raise MissionBlocked((f"cannot pause terminal mission {status.value}",))
        self.store.transition(mission_id, MissionStatus.PAUSED, principal=principal, reason=reason)
        self._emit(EventType.MISSION_PAUSED, {"mission_id": mission_id, "principal": principal, "reason": reason})
        return self._execution(self.store.get_plan(mission_id))

    def cancel(self, mission_id: str, *, principal: str, reason: str) -> MissionExecution:
        status = self.store.current_status(mission_id)
        if status == MissionStatus.COMPLETED:
            raise MissionBlocked(("completed mission cannot be cancelled",))
        self.store.transition(mission_id, MissionStatus.CANCELLED, principal=principal, reason=reason)
        self._emit(EventType.MISSION_CANCELLED, {"mission_id": mission_id, "principal": principal, "reason": reason}, severity="warning")
        return self._execution(self.store.get_plan(mission_id))

    def record_value_evidence(
        self,
        *,
        mission_id: str,
        kind: MissionValueKind,
        description: str,
        source: str,
        amount_usd: float | None = None,
        external_reference: str | None = None,
        related_evidence_id: str | None = None,
        verified_by: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> MissionValueEvidence:
        blockers: list[str] = []
        if not description.strip() or not source.strip():
            blockers.append("value evidence description and source are required")
        if amount_usd is not None and amount_usd < 0:
            blockers.append("value amount cannot be negative")
        if kind in {MissionValueKind.REALIZED, MissionValueKind.VERIFIED} and not external_reference:
            blockers.append("realized and verified value require an external evidence reference")
        if kind == MissionValueKind.VERIFIED:
            if not verified_by or verified_by.casefold() not in {item.casefold() for item in self.governor.trusted_principals}:
                blockers.append("verified value requires a trusted Founder/operator verifier")
            if not related_evidence_id:
                blockers.append("verified value must reference realized evidence")
            else:
                related = self.store.get_value_evidence(related_evidence_id)
                if related.mission_id != mission_id or related.kind != MissionValueKind.REALIZED:
                    blockers.append("verified value must reference realized evidence from the same mission")
                if amount_usd is not None and related.amount_usd is not None and amount_usd > related.amount_usd:
                    blockers.append("verified amount cannot exceed related realized amount")
        if blockers:
            raise MissionBlocked(blockers)
        item = self.store.add_value_evidence(MissionValueEvidence(
            mission_id=mission_id, kind=kind, description=description, source=source,
            amount_usd=amount_usd, external_reference=external_reference,
            related_evidence_id=related_evidence_id, verified_by=verified_by,
            metadata=dict(metadata or {}), observed_at=utc_now(),
        ))
        self._emit(EventType.MISSION_VALUE_RECORDED, {"mission_id": mission_id, "evidence_id": item.evidence_id, "kind": kind.value, "amount_usd": amount_usd})
        return item

    async def finalize(self, mission_id: str, *, achieved: bool, summary: str, lessons: Sequence[str], principal: str) -> MissionOutcome:
        decision_blockers = self.governor.validate_decision(principal=principal, reason=summary)
        if decision_blockers:
            raise MissionBlocked(decision_blockers)
        status = self.store.current_status(mission_id)
        if status not in {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.STOPPED, MissionStatus.CANCELLED}:
            raise MissionBlocked((f"mission outcome requires terminal execution state; current status is {status.value}",))
        if self.store.latest_outcome(mission_id) is not None:
            raise MissionBlocked(("mission outcome is already finalized",))
        plan = self.store.get_plan(mission_id)
        evidence = self.store.value_evidence(mission_id)
        claimed = sum(item.amount_usd or 0.0 for item in evidence if item.kind == MissionValueKind.CLAIMED)
        realized = sum(item.amount_usd or 0.0 for item in evidence if item.kind == MissionValueKind.REALIZED)
        verified = sum(item.amount_usd or 0.0 for item in evidence if item.kind == MissionValueKind.VERIFIED)
        state = MissionOutcomeState.VERIFIED if verified > 0 else MissionOutcomeState.REALIZED if realized > 0 else MissionOutcomeState.CLAIMED if claimed > 0 else MissionOutcomeState.NO_VALUE
        outcome = self.store.add_outcome(MissionOutcome(
            mission_id=mission_id, state=state, achieved=achieved, summary=summary,
            claimed_value_usd=claimed, realized_revenue_usd=realized, verified_revenue_usd=verified,
            evidence_ids=tuple(item.evidence_id for item in evidence), lessons=tuple(str(item) for item in lessons),
            metadata={"principal": principal, "lane": plan.lane.value, "claimed_is_not_revenue": True}, created_at=utc_now(),
        ))
        self._emit(EventType.MISSION_OUTCOME_RECORDED, {
            "mission_id": mission_id, "outcome_id": outcome.outcome_id, "state": outcome.state.value,
            "claimed_value_usd": claimed, "realized_revenue_usd": realized, "verified_revenue_usd": verified,
        })
        if self.memory_fabric is not None:
            record = await self.memory_fabric.remember(MemoryRecord(
                key=f"mission:{mission_id}:outcome:{outcome.outcome_id}",
                value={"outcome_id": outcome.outcome_id, "mission_id": mission_id, "summary": summary, "lessons": list(lessons)},
                namespace="episodes", kind=MemoryKind.REFLECTION,
                content=f"Mission {mission_id} outcome: {summary}\nLessons: " + "; ".join(lessons),
                metadata={"mission_id": mission_id, "outcome_id": outcome.outcome_id, "knowledge_candidate": True, "promotion_required": True},
                provenance=MemoryProvenance(source="mission-outcome", observed_at=utc_now(), evidence_links=tuple(item.evidence_id for item in evidence)),
            ))
            self._emit(EventType.MISSION_KNOWLEDGE_CANDIDATE_RECORDED, {"mission_id": mission_id, "record_id": record.record_id})
        return outcome

    async def _fail(self, plan: MissionPlan, step: MissionStep, error: str, fingerprint: str | None, principal: str) -> MissionExecution:
        self.store.transition(plan.mission_id, MissionStatus.FAILED, principal=principal, reason=error, metadata={"step_id": step.step_id, "failure_fingerprint": fingerprint})
        self._emit(EventType.MISSION_FAILED, {"mission_id": plan.mission_id, "step_id": step.step_id, "error": error, "failure_fingerprint": fingerprint}, severity="error")
        if self.evolution_engine is not None:
            trigger = self.evolution_engine.register_trigger(EvolutionTrigger(
                trigger_type=EvolutionTriggerType.FAILURE,
                fingerprint=fingerprint or self._mission_fingerprint(plan.mission_id, step.step_id, error),
                summary=f"Mission {plan.mission_id} failed at step {step.title}: {error}",
                evidence_ids=(plan.mission_id, step.step_id),
                metadata={"source": "mission-orchestrator", "lane": plan.lane.value, "authority": "learning-trigger-only"},
            ))
            self._emit(EventType.MISSION_CEE_LEARNING_TRIGGERED, {"mission_id": plan.mission_id, "trigger_id": trigger.trigger_id, "authority": "learning-trigger-only"}, severity="warning")
        return self._execution(plan, current_step_id=step.step_id, blockers=(error,))

    def _stop(self, plan: MissionPlan, blockers: Sequence[str], *, principal: str) -> MissionExecution:
        self.store.transition(plan.mission_id, MissionStatus.STOPPED, principal=principal, reason="; ".join(blockers), metadata={"stop_conditions": list(blockers)})
        self._emit(EventType.MISSION_STOPPED, {"mission_id": plan.mission_id, "blockers": list(blockers)}, severity="warning")
        return self._execution(plan, blockers=tuple(blockers))

    def _completed_step_ids(self, plan: MissionPlan) -> set[str]:
        result: set[str] = set()
        for step in plan.steps:
            latest = self.store.latest_attempt(plan.mission_id, step.step_id)
            if latest and latest.status == MissionStepStatus.COMPLETED:
                result.add(step.step_id)
        return result

    @staticmethod
    def _next_step(plan: MissionPlan, completed: set[str]) -> MissionStep | None:
        for step in sorted(plan.steps, key=lambda item: item.step_order):
            if step.step_id in completed:
                continue
            if set(step.depends_on).issubset(completed):
                return step
        return None

    def _next_attempt_number(self, mission_id: str, step_id: str) -> int:
        attempts = self.store.attempts(mission_id, step_id=step_id)
        numbers = {item.attempt_number for item in attempts}
        return max(numbers, default=0) + 1

    def _budget_blockers(self, plan: MissionPlan) -> tuple[str, ...]:
        attempts = self.store.attempts(plan.mission_id)
        unique: dict[tuple[str, int], MissionStepAttempt] = {}
        for item in attempts:
            unique[(item.step_id, item.attempt_number)] = item
        spent = sum(item.estimated_cost_usd for item in unique.values())
        blockers: list[str] = []
        if spent > plan.budget.max_cost_usd:
            blockers.append("mission cost budget exceeded")
        if len(unique) >= plan.budget.max_step_attempts:
            blockers.append("mission step-attempt budget exhausted")
        transitions = list(reversed(self.store.transitions(plan.mission_id, limit=5000)))
        started = next((item.created_at for item in transitions if item.to_status == MissionStatus.RUNNING), None)
        if started:
            elapsed = (datetime.now(timezone.utc) - self._parse_time(started)).total_seconds()
            if elapsed > plan.budget.max_duration_seconds:
                blockers.append("mission duration budget exceeded")
        return tuple(blockers)

    def _execution(self, plan: MissionPlan, *, current_step_id: str | None = None, approval_id: str | None = None,
                   blockers: Sequence[str] = (), metadata: Mapping[str, Any] | None = None) -> MissionExecution:
        return MissionExecution(
            mission_id=plan.mission_id, status=self.store.current_status(plan.mission_id),
            completed_step_ids=tuple(sorted(self._completed_step_ids(plan))), current_step_id=current_step_id,
            approval_id=approval_id, blockers=tuple(blockers), metadata=dict(metadata or {}),
        )

    @staticmethod
    def _parse_time(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _mission_fingerprint(mission_id: str, step_id: str, error: str) -> str:
        import hashlib
        return hashlib.sha256(f"{mission_id}:{step_id}:{' '.join(error.casefold().split())}".encode("utf-8")).hexdigest()

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, severity: str = "info") -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type, actor=self.orchestrator_id, payload=dict(payload), severity=severity)
