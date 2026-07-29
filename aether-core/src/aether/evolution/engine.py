"""Governed internal evolution orchestration.

The engine owns evidence, policy, decisions, and lineage. Candidate generation,
sandbox execution, and production mutation remain replaceable ports.
"""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import replace
from typing import Iterable

from aether.contracts.event_types import EventType
from aether.contracts.evolution import (
    EvolutionCandidate, EvolutionCandidateStatus, EvolutionCommand, EvolutionDecision,
    EvolutionDecisionType, EvolutionEvaluation, EvolutionLearning, EvolutionLineage,
    EvolutionPromoter, EvolutionSandbox, EvolutionTargetType, EvolutionTrigger,
    candidate_semantic_hash, content_hash,
)
from aether.events import EventBus
from aether.evolution.governance import EvolutionBlocked, InternalEvolutionGovernor
from aether.evolution.store import EvolutionDecisionConflict, SQLiteEvolutionStore
from aether.utils.time import utc_now


class InternalEvolutionEngine:
    engine_id = "aether.evolution.internal"

    def __init__(
        self,
        store: SQLiteEvolutionStore,
        *,
        governor: InternalEvolutionGovernor | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store
        self.governor = governor or InternalEvolutionGovernor()
        self.event_bus = event_bus

    def register_trigger(self, trigger: EvolutionTrigger) -> EvolutionTrigger:
        prior = self.store.learnings_for_fingerprint(trigger.fingerprint)
        normalized = replace(
            trigger,
            prior_learning_ids=tuple(item.learning_id for item in prior),
            created_at=trigger.created_at or utc_now(),
        )
        saved = self.store.add_trigger(normalized)
        self._emit(EventType.EVOLUTION_TRIGGER_REGISTERED, {
            "trigger_id": saved.trigger_id,
            "trigger_type": saved.trigger_type.value,
            "fingerprint": saved.fingerprint,
            "summary": saved.summary,
            "prior_learning_ids": list(saved.prior_learning_ids),
        })
        return saved

    def propose_candidate(
        self,
        *,
        trigger_id: str,
        target_type: EvolutionTargetType,
        target_path: str,
        baseline_content: str,
        candidate_content: str,
        rationale: str,
        generator_id: str,
        deterministic_checks: Iterable[EvolutionCommand],
        heldout_checks: Iterable[EvolutionCommand],
        retry_reason: str | None = None,
        metadata: dict | None = None,
    ) -> EvolutionCandidate:
        trigger = self.store.get_trigger(trigger_id)
        diff = "\n".join(difflib.unified_diff(
            baseline_content.splitlines(), candidate_content.splitlines(),
            fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm="",
        ))
        candidate = EvolutionCandidate(
            trigger_id=trigger.trigger_id,
            trigger_fingerprint=trigger.fingerprint,
            target_type=target_type,
            target_path=target_path.replace("\\", "/"),
            baseline_hash=content_hash(baseline_content),
            candidate_hash=content_hash(candidate_content),
            baseline_content=baseline_content,
            candidate_content=candidate_content,
            diff=diff,
            rationale=rationale,
            generator_id=generator_id,
            deterministic_checks=tuple(deterministic_checks),
            heldout_checks=tuple(heldout_checks),
            retry_reason=retry_reason,
            metadata=dict(metadata or {}),
        )
        blockers = self.governor.validate_candidate(candidate)
        if blockers:
            raise EvolutionBlocked(blockers)
        semantic_hash = candidate_semantic_hash(candidate)
        for previous in self.store.candidates_for_fingerprint(trigger.fingerprint):
            if candidate_semantic_hash(previous) != semantic_hash:
                continue
            evaluation = self.store.get_evaluation(previous.candidate_id)
            decision = self.store.get_decision(previous.candidate_id)
            failed_before = bool(evaluation and not evaluation.passed) or bool(
                decision and decision.decision == EvolutionDecisionType.REJECT
            )
            if failed_before and not (retry_reason or "").strip():
                raise EvolutionBlocked((
                    "the same failed candidate cannot be repeated without an explicit retry reason",
                ))
        attempt_hash = semantic_hash
        if (retry_reason or "").strip():
            normalized_reason = " ".join(str(retry_reason).casefold().split())
            attempt_hash = hashlib.sha256(f"{semantic_hash}:{normalized_reason}".encode("utf-8")).hexdigest()
        saved = self.store.add_candidate(candidate, attempt_hash)
        self._emit(EventType.IMPROVEMENT_PROPOSED, {
            "candidate_id": saved.candidate_id,
            "trigger_id": saved.trigger_id,
            "target_path": saved.target_path,
            "baseline_hash": saved.baseline_hash,
            "candidate_hash": saved.candidate_hash,
            "generator_id": saved.generator_id,
            "diff": saved.diff,
        })
        return saved

    async def evaluate(self, candidate_id: str, sandbox: EvolutionSandbox) -> EvolutionEvaluation:
        candidate = self.store.get_candidate(candidate_id)
        existing = self.store.get_evaluation(candidate_id)
        if existing is not None:
            return existing
        evaluation = await sandbox.evaluate(candidate)
        blockers = self.governor.validate_evaluation(evaluation)
        normalized = replace(
            evaluation,
            passed=not blockers,
            blockers=tuple(dict.fromkeys((*evaluation.blockers, *blockers))),
            created_at=evaluation.created_at or utc_now(),
        )
        saved = self.store.add_evaluation(normalized)
        self._emit(
            EventType.IMPROVEMENT_VERIFIED if saved.passed else EventType.EVOLUTION_EVALUATION_FAILED,
            {
                "candidate_id": candidate_id,
                "evaluation_id": saved.evaluation_id,
                "baseline_score": saved.baseline_score,
                "candidate_score": saved.candidate_score,
                "improvement": saved.improvement,
                "regression_count": saved.regression_count,
                "passed": saved.passed,
                "blockers": list(saved.blockers),
            },
            severity="info" if saved.passed else "warning",
        )
        if not saved.passed:
            self.store.add_learning(EvolutionLearning(
                fingerprint=candidate.trigger_fingerprint,
                outcome="evaluation-failed",
                summary="Candidate failed governed evaluation: " + "; ".join(saved.blockers),
                candidate_id=candidate_id,
                metadata={"evaluation_id": saved.evaluation_id},
            ))
        return saved

    async def decide(
        self,
        candidate_id: str,
        *,
        approved: bool,
        principal: str,
        channel: str,
        reason: str,
        promoter: EvolutionPromoter | None = None,
    ) -> EvolutionCandidate:
        candidate = self.store.get_candidate(candidate_id)
        existing = self.store.get_decision(candidate_id)
        requested = EvolutionDecisionType.PROMOTE if approved else EvolutionDecisionType.REJECT
        if existing is not None:
            if existing.decision != requested:
                raise EvolutionDecisionConflict(
                    f"candidate {candidate_id} already has terminal decision {existing.decision.value}"
                )
            return self.store.get_candidate(candidate_id)
        decision_blockers = self.governor.validate_decision(principal=principal, reason=reason)
        if decision_blockers:
            raise EvolutionBlocked(decision_blockers)
        if not approved:
            decision = self.store.decide(EvolutionDecision(
                candidate_id=candidate_id,
                decision=EvolutionDecisionType.REJECT,
                principal=principal,
                channel=channel,
                reason=reason,
            ))
            self.store.add_learning(EvolutionLearning(
                fingerprint=candidate.trigger_fingerprint,
                outcome="rejected",
                summary=reason,
                candidate_id=candidate_id,
                metadata={"decision_id": decision.decision_id},
            ))
            self._emit(EventType.EVOLUTION_IMPROVEMENT_REJECTED, {
                "candidate_id": candidate_id,
                "decision_id": decision.decision_id,
                "principal": principal,
                "reason": reason,
            })
            return self.store.get_candidate(candidate_id)

        evaluation = self.store.get_evaluation(candidate_id)
        if evaluation is None:
            raise EvolutionBlocked(("candidate has not been evaluated",))
        evaluation_blockers = self.governor.validate_evaluation(evaluation)
        if evaluation_blockers:
            raise EvolutionBlocked(evaluation_blockers)
        if promoter is None:
            raise EvolutionBlocked(("a production promoter adapter is required",))

        receipt = await promoter.promote(candidate)
        lineage = EvolutionLineage(
            candidate_id=candidate_id,
            target_path=receipt.target_path,
            parent_hash=receipt.parent_hash,
            promoted_hash=receipt.promoted_hash,
            backup_path=receipt.backup_path,
            principal=principal,
            reason=reason,
        )
        try:
            lineage = self.store.add_lineage(lineage)
            decision = self.store.decide(EvolutionDecision(
                candidate_id=candidate_id,
                decision=EvolutionDecisionType.PROMOTE,
                principal=principal,
                channel=channel,
                reason=reason,
                lineage_id=lineage.lineage_id,
            ))
        except Exception:
            await promoter.rollback(lineage)
            raise
        self.store.add_learning(EvolutionLearning(
            fingerprint=candidate.trigger_fingerprint,
            outcome="promoted",
            summary=reason,
            candidate_id=candidate_id,
            lineage_id=lineage.lineage_id,
            metadata={
                "evaluation_id": evaluation.evaluation_id,
                "decision_id": decision.decision_id,
                "improvement": evaluation.improvement,
            },
        ))
        self._emit(EventType.EVOLUTION_IMPROVEMENT_PROMOTED, {
            "candidate_id": candidate_id,
            "decision_id": decision.decision_id,
            "lineage_id": lineage.lineage_id,
            "target_path": lineage.target_path,
            "parent_hash": lineage.parent_hash,
            "promoted_hash": lineage.promoted_hash,
            "principal": principal,
        })
        return self.store.get_candidate(candidate_id)

    async def rollback(
        self,
        lineage_id: str,
        *,
        principal: str,
        channel: str,
        reason: str,
        promoter: EvolutionPromoter,
    ) -> EvolutionLineage:
        blockers = self.governor.validate_decision(principal=principal, reason=reason)
        if blockers:
            raise EvolutionBlocked(blockers)
        lineage = self.store.get_lineage(lineage_id)
        if lineage.rolled_back_at:
            return lineage
        await promoter.rollback(lineage)
        updated = self.store.add_rollback(lineage_id, principal=principal, reason=reason)
        candidate = self.store.get_candidate(lineage.candidate_id)
        self.store.add_learning(EvolutionLearning(
            fingerprint=candidate.trigger_fingerprint,
            outcome="rolled-back",
            summary=reason,
            candidate_id=candidate.candidate_id,
            lineage_id=lineage_id,
            metadata={"channel": channel},
        ))
        self._emit(EventType.EVOLUTION_IMPROVEMENT_ROLLED_BACK, {
            "candidate_id": candidate.candidate_id,
            "lineage_id": lineage_id,
            "principal": principal,
            "reason": reason,
        }, severity="warning")
        return updated

    def status(self) -> dict:
        candidates = self.store.list_candidates(limit=1000)
        return {
            "triggers": len(self.store.list_triggers(limit=1000)),
            "candidates": len(candidates),
            "proposed": sum(item.status == EvolutionCandidateStatus.PROPOSED for item in candidates),
            "verified": sum(item.status == EvolutionCandidateStatus.VERIFIED for item in candidates),
            "promoted": sum(item.status == EvolutionCandidateStatus.PROMOTED for item in candidates),
            "rejected": sum(item.status == EvolutionCandidateStatus.REJECTED for item in candidates),
            "rolled_back": sum(item.status == EvolutionCandidateStatus.ROLLED_BACK for item in candidates),
        }

    def _emit(self, event_type: str, payload: dict, *, severity: str = "info") -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type=event_type, actor=self.engine_id, payload=payload, severity=severity)
