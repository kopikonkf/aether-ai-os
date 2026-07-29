"""Governed skill factory, activation registry, telemetry, and curator lifecycle."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

from aether.contracts.event_types import EventType
from aether.contracts.skills import (
    SkillBenchmark, SkillBenchmarkSandbox, SkillCandidate, SkillDecision, SkillDecisionType,
    SkillInstaller, SkillLifecycleAction, SkillLifecycleEvent, SkillLifecycleReview,
    SkillLifecycleStatus, SkillManifest, SkillProvenance, SkillRecord, SkillTriggerType,
    SkillUsageEvent, skill_candidate_semantic_hash,
)
from aether.events import EventBus
from aether.skills.governance import SkillFactoryBlocked, SkillFactoryGovernor
from aether.skills.store import SQLiteSkillStore, SkillDecisionConflict
from aether.utils.time import utc_now


class SkillFactory:
    factory_id = "aether.skill-factory"

    def __init__(
        self,
        store: SQLiteSkillStore,
        *,
        governor: SkillFactoryGovernor | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store
        self.governor = governor or SkillFactoryGovernor()
        self.event_bus = event_bus

    def propose(
        self,
        *,
        manifest: SkillManifest,
        provenance: SkillProvenance,
        deterministic_checks,
        heldout_checks,
        rationale: str,
        retry_reason: str | None = None,
    ) -> SkillCandidate:
        baseline = self.store.get_record(provenance.prior_skill_id) if provenance.prior_skill_id else None
        candidate = SkillCandidate(
            manifest=manifest,
            provenance=provenance,
            deterministic_checks=tuple(deterministic_checks),
            heldout_checks=tuple(heldout_checks),
            rationale=rationale,
            retry_reason=retry_reason,
        )
        blockers = self.governor.validate_candidate(candidate, baseline)
        if blockers:
            raise SkillFactoryBlocked(blockers)
        semantic_hash = skill_candidate_semantic_hash(candidate)
        for previous in self.store.candidates_for_name(manifest.name):
            if skill_candidate_semantic_hash(previous) != semantic_hash:
                continue
            benchmark = self.store.get_benchmark(previous.candidate_id)
            decision = self.store.get_decision(previous.candidate_id)
            failed = bool(benchmark and not benchmark.passed) or bool(
                decision and decision.decision == SkillDecisionType.REJECT
            )
            if failed and not (retry_reason or "").strip():
                raise SkillFactoryBlocked((
                    "the same failed skill candidate cannot be repeated without an explicit retry reason",
                ))
        attempt_hash = semantic_hash
        if (retry_reason or "").strip():
            normalized = " ".join(str(retry_reason).casefold().split())
            attempt_hash = hashlib.sha256(f"{semantic_hash}:{normalized}".encode("utf-8")).hexdigest()
        saved = self.store.add_candidate(candidate, attempt_hash)
        self._emit(EventType.SKILL_CANDIDATE_PROPOSED, {
            "candidate_id": saved.candidate_id,
            "name": manifest.name,
            "version": manifest.version,
            "artifact_hash": saved.artifact_hash,
            "trigger_type": provenance.trigger_type.value,
            "trigger_fingerprint": provenance.trigger_fingerprint,
            "evidence_ids": list(provenance.evidence_ids),
            "generator_id": provenance.generator_id,
        })
        return saved

    def propose_repeated_workflow(
        self,
        *,
        manifest: SkillManifest,
        workflow_fingerprint: str,
        evidence_ids: Iterable[str],
        observed_count: int,
        successful_count: int,
        source_workflow: str,
        generator_id: str,
        deterministic_checks,
        heldout_checks,
        rationale: str,
    ) -> SkillCandidate:
        return self.propose(
            manifest=manifest,
            provenance=SkillProvenance(
                trigger_type=SkillTriggerType.REPEATED_SUCCESS,
                trigger_fingerprint=workflow_fingerprint,
                evidence_ids=tuple(evidence_ids),
                observed_count=observed_count,
                successful_count=successful_count,
                source_workflow=source_workflow,
                generator_id=generator_id,
            ),
            deterministic_checks=deterministic_checks,
            heldout_checks=heldout_checks,
            rationale=rationale,
        )

    def propose_capability_gap(
        self,
        *,
        manifest: SkillManifest,
        gap_fingerprint: str,
        evidence_ids: Iterable[str],
        generator_id: str,
        deterministic_checks,
        heldout_checks,
        rationale: str,
    ) -> SkillCandidate:
        normalized_evidence = tuple(evidence_ids)
        return self.propose(
            manifest=manifest,
            provenance=SkillProvenance(
                trigger_type=SkillTriggerType.CAPABILITY_GAP,
                trigger_fingerprint=gap_fingerprint,
                evidence_ids=normalized_evidence,
                observed_count=max(1, len(normalized_evidence)),
                successful_count=0,
                generator_id=generator_id,
            ),
            deterministic_checks=deterministic_checks,
            heldout_checks=heldout_checks,
            rationale=rationale,
        )

    def propose_revision(
        self,
        *,
        prior_skill_id: str,
        manifest: SkillManifest,
        evidence_ids: Iterable[str],
        generator_id: str,
        deterministic_checks,
        heldout_checks,
        rationale: str,
        retry_reason: str | None = None,
    ) -> SkillCandidate:
        prior = self.store.get_record(prior_skill_id)
        return self.propose(
            manifest=manifest,
            provenance=SkillProvenance(
                trigger_type=SkillTriggerType.REVISION,
                trigger_fingerprint=f"revision:{prior.artifact_hash}",
                evidence_ids=tuple(evidence_ids),
                observed_count=len(self.store.usages(prior_skill_id)),
                successful_count=sum(item.success for item in self.store.usages(prior_skill_id)),
                source_workflow=prior.manifest.name,
                generator_id=generator_id,
                prior_skill_id=prior_skill_id,
            ),
            deterministic_checks=deterministic_checks,
            heldout_checks=heldout_checks,
            rationale=rationale,
            retry_reason=retry_reason,
        )

    async def benchmark(self, candidate_id: str, sandbox: SkillBenchmarkSandbox) -> SkillBenchmark:
        candidate = self.store.get_candidate(candidate_id)
        existing = self.store.get_benchmark(candidate_id)
        if existing is not None:
            return existing
        baseline = self.store.get_record(candidate.provenance.prior_skill_id) if candidate.provenance.prior_skill_id else None
        result = await sandbox.benchmark(candidate, baseline)
        blockers = self.governor.validate_benchmark(result)
        normalized = replace(
            result,
            passed=not blockers,
            blockers=tuple(dict.fromkeys((*result.blockers, *blockers))),
            created_at=result.created_at or utc_now(),
        )
        saved = self.store.add_benchmark(normalized)
        self.store.add_learning(
            fingerprint=candidate.provenance.trigger_fingerprint,
            outcome="benchmark-passed" if saved.passed else "benchmark-failed",
            summary=("Skill benchmark passed." if saved.passed else "Skill benchmark failed: " + "; ".join(saved.blockers)),
            candidate_id=candidate_id,
            metadata={"benchmark_id": saved.benchmark_id, "improvement": saved.improvement},
        )
        self._emit(
            EventType.SKILL_BENCHMARK_PASSED if saved.passed else EventType.SKILL_BENCHMARK_FAILED,
            {
                "candidate_id": candidate_id,
                "benchmark_id": saved.benchmark_id,
                "baseline_score": saved.baseline_score,
                "candidate_score": saved.candidate_score,
                "improvement": saved.improvement,
                "regression_count": saved.regression_count,
                "blockers": list(saved.blockers),
            },
            severity="info" if saved.passed else "warning",
        )
        return saved

    async def decide(
        self,
        candidate_id: str,
        *,
        approved: bool,
        principal: str,
        channel: str,
        reason: str,
        installer: SkillInstaller | None = None,
    ) -> SkillCandidate:
        candidate = self.store.get_candidate(candidate_id)
        existing = self.store.get_decision(candidate_id)
        requested = SkillDecisionType.ACTIVATE if approved else SkillDecisionType.REJECT
        if existing is not None:
            if existing.decision != requested:
                raise SkillDecisionConflict(
                    f"candidate {candidate_id} already has terminal decision {existing.decision.value}"
                )
            return self.store.get_candidate(candidate_id)
        blockers = self.governor.validate_activation(principal=principal, reason=reason)
        if blockers:
            raise SkillFactoryBlocked(blockers)
        if not approved:
            decision = self.store.add_decision(SkillDecision(
                candidate_id=candidate_id,
                decision=SkillDecisionType.REJECT,
                principal=principal,
                channel=channel,
                reason=reason,
            ))
            self.store.add_learning(
                fingerprint=candidate.provenance.trigger_fingerprint,
                outcome="rejected",
                summary=reason,
                candidate_id=candidate_id,
                metadata={"decision_id": decision.decision_id},
            )
            self._emit(EventType.SKILL_CANDIDATE_REJECTED, {
                "candidate_id": candidate_id,
                "principal": principal,
                "reason": reason,
            })
            return self.store.get_candidate(candidate_id)

        benchmark = self.store.get_benchmark(candidate_id)
        if benchmark is None:
            raise SkillFactoryBlocked(("skill candidate has not been benchmarked",))
        benchmark_blockers = self.governor.validate_benchmark(benchmark)
        if benchmark_blockers:
            raise SkillFactoryBlocked(benchmark_blockers)
        if installer is None:
            raise SkillFactoryBlocked(("a runtime skill installer adapter is required",))

        prior = self.store.active_for_name(candidate.manifest.name)
        if prior is not None and candidate.provenance.prior_skill_id != prior.skill_id:
            raise SkillFactoryBlocked((
                "an active skill with this name already exists; replacement must be a revision bound to prior_skill_id",
            ))
        receipt = await installer.install(candidate)
        record = SkillRecord(
            candidate_id=candidate_id,
            manifest=candidate.manifest,
            provenance=candidate.provenance,
            artifact_hash=candidate.artifact_hash,
            principal=principal,
            reason=reason,
            install_receipt=receipt,
        )
        try:
            record = self.store.add_record(record)
            decision = self.store.add_decision(SkillDecision(
                candidate_id=candidate_id,
                decision=SkillDecisionType.ACTIVATE,
                principal=principal,
                channel=channel,
                reason=reason,
                skill_id=record.skill_id,
            ))
            if prior is not None and prior.skill_id != record.skill_id:
                self.store.add_lifecycle(SkillLifecycleEvent(
                    skill_id=prior.skill_id,
                    action=SkillLifecycleAction.SUPERSEDE,
                    principal=principal,
                    channel=channel,
                    reason=f"Superseded by activated skill {record.skill_id}: {reason}",
                ))
        except Exception:
            await installer.rollback_install(receipt)
            raise
        self.store.add_learning(
            fingerprint=candidate.provenance.trigger_fingerprint,
            outcome="activated",
            summary=reason,
            skill_id=record.skill_id,
            candidate_id=candidate_id,
            metadata={"decision_id": decision.decision_id, "benchmark_id": benchmark.benchmark_id},
        )
        self._emit(EventType.SKILL_ACTIVATED, {
            "candidate_id": candidate_id,
            "skill_id": record.skill_id,
            "name": record.manifest.name,
            "version": record.manifest.version,
            "artifact_hash": record.artifact_hash,
            "adapter_id": receipt.adapter_id,
            "principal": principal,
        })
        return self.store.get_candidate(candidate_id)

    def record_usage(self, usage: SkillUsageEvent) -> SkillUsageEvent:
        record = self.store.get_record(usage.skill_id)
        if record.lifecycle_status in {SkillLifecycleStatus.ARCHIVED, SkillLifecycleStatus.SUPERSEDED}:
            raise SkillFactoryBlocked((f"skill is not executable in lifecycle state {record.lifecycle_status.value}",))
        saved = self.store.add_usage(usage)
        self._emit(EventType.SKILL_USAGE_RECORDED, {
            "skill_id": saved.skill_id,
            "usage_id": saved.usage_id,
            "runtime_id": saved.runtime_id,
            "success": saved.success,
            "duration_seconds": saved.duration_seconds,
            "error_fingerprint": saved.error_fingerprint,
        }, severity="info" if saved.success else "warning")
        return saved

    def review(self, skill_id: str, *, now: datetime | None = None) -> SkillLifecycleReview:
        record = self.store.get_record(skill_id)
        usages = self.store.usages(skill_id)
        usage_count = len(usages)
        success_rate = sum(item.success for item in usages) / usage_count if usage_count else 0.0
        last_used_at = usages[0].used_at if usages else None
        reasons: list[str] = []
        recommended = record.lifecycle_status
        current_time = now or datetime.now(timezone.utc)
        if record.lifecycle_status == SkillLifecycleStatus.ACTIVE:
            reference = _parse_time(last_used_at or record.activated_at)
            if current_time - reference >= timedelta(days=self.governor.policy.stale_after_days_without_usage):
                recommended = SkillLifecycleStatus.STALE
                reasons.append("skill has not been used within the configured freshness window")
            if usage_count >= self.governor.policy.minimum_usage_for_failure_review:
                failure_rate = 1.0 - success_rate
                if failure_rate > self.governor.policy.maximum_failure_rate:
                    recommended = SkillLifecycleStatus.STALE
                    reasons.append("skill failure rate exceeds curator policy")
        return SkillLifecycleReview(
            skill_id=skill_id,
            current_status=record.lifecycle_status,
            recommended_status=recommended,
            usage_count=usage_count,
            success_rate=success_rate,
            last_used_at=last_used_at,
            reasons=tuple(reasons),
        )

    async def apply_review(self, skill_id: str, *, now: datetime | None = None) -> SkillRecord:
        review = self.review(skill_id, now=now)
        if review.recommended_status == SkillLifecycleStatus.STALE and review.current_status == SkillLifecycleStatus.ACTIVE:
            event = self.store.add_lifecycle(SkillLifecycleEvent(
                skill_id=skill_id,
                action=SkillLifecycleAction.MARK_STALE,
                principal="curator",
                channel="internal",
                reason="Curator marked skill stale from bounded usage telemetry review.",
            ))
            self._emit(EventType.SKILL_MARKED_STALE, {
                "skill_id": skill_id,
                "lifecycle_id": event.lifecycle_id,
                "reasons": list(review.reasons),
                "usage_count": review.usage_count,
                "success_rate": review.success_rate,
            }, severity="warning")
        return self.store.get_record(skill_id)

    async def lifecycle(
        self,
        skill_id: str,
        *,
        action: SkillLifecycleAction,
        principal: str,
        channel: str,
        reason: str,
        installer: SkillInstaller | None = None,
        benchmark_passed: bool = False,
    ) -> SkillRecord:
        record = self.store.get_record(skill_id)
        if action == SkillLifecycleAction.ARCHIVE and record.lifecycle_status == SkillLifecycleStatus.ARCHIVED:
            return record
        if action == SkillLifecycleAction.MARK_STALE and record.lifecycle_status == SkillLifecycleStatus.STALE:
            return record
        blockers = self.governor.validate_lifecycle(
            action, principal=principal, reason=reason, record=record, benchmark_passed=benchmark_passed
        )
        if blockers:
            raise SkillFactoryBlocked(blockers)
        if action == SkillLifecycleAction.ARCHIVE and installer is not None:
            await installer.deactivate(record, reason=reason)
        event = self.store.add_lifecycle(SkillLifecycleEvent(
            skill_id=skill_id,
            action=action,
            principal=principal,
            channel=channel,
            reason=reason,
        ))
        event_type = {
            SkillLifecycleAction.MARK_STALE: EventType.SKILL_MARKED_STALE,
            SkillLifecycleAction.ARCHIVE: EventType.SKILL_ARCHIVED,
            SkillLifecycleAction.REACTIVATE: EventType.SKILL_REACTIVATED,
            SkillLifecycleAction.SUPERSEDE: EventType.SKILL_SUPERSEDED,
        }[action]
        self._emit(event_type, {
            "skill_id": skill_id,
            "lifecycle_id": event.lifecycle_id,
            "principal": principal,
            "reason": reason,
        })
        return self.store.get_record(skill_id)

    def status(self) -> dict:
        candidates = self.store.list_candidates(limit=1000)
        records = self.store.list_records(limit=1000)
        return {
            "candidates": len(candidates),
            "draft": sum(item.status.value == "draft" for item in candidates),
            "verified": sum(item.status.value == "verified" for item in candidates),
            "rejected": sum(item.status.value == "rejected" for item in candidates),
            "activated_candidates": sum(item.status.value == "active" for item in candidates),
            "skills": len(records),
            "active": sum(item.lifecycle_status == SkillLifecycleStatus.ACTIVE for item in records),
            "stale": sum(item.lifecycle_status == SkillLifecycleStatus.STALE for item in records),
            "archived": sum(item.lifecycle_status == SkillLifecycleStatus.ARCHIVED for item in records),
            "superseded": sum(item.lifecycle_status == SkillLifecycleStatus.SUPERSEDED for item in records),
        }

    def _emit(self, event_type: str, payload: dict, *, severity: str = "info") -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type=event_type, actor=self.factory_id, payload=payload, severity=severity)


def _parse_time(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
