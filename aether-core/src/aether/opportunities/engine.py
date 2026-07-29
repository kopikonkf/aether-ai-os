"""Autonomous evidence synthesis, portfolio scoring, and progressive-autonomy mandates."""
from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from aether.contracts.event_types import EventType
from aether.contracts.opportunities import (
    AutonomyLevel, ClaimStance, ContentSnapshot, EvidenceStrength, ExperimentMandate,
    ExtractedClaim, MandateStatus, OpportunityBlocked, OpportunityCandidate, OpportunityScore,
    OpportunityStatus, PortfolioDecision, PortfolioDecisionType, PortfolioPolicy, PortfolioSelection,
    SourceAdapterManifest, SourceAdapterStatus, claim_hash, mandate_hash,
    opportunity_candidate_hash, portfolio_policy_fingerprint, source_manifest_hash,
)
from aether.events import EventBus
from aether.opportunities.store import SQLiteOpportunityStore
from aether.utils.time import utc_now


_STRENGTH_WEIGHT = {
    EvidenceStrength.WEAK: 0.35,
    EvidenceStrength.MODERATE: 0.65,
    EvidenceStrength.STRONG: 0.75,
    EvidenceStrength.VERIFIED: 1.0,
}


class OpportunityGovernor:
    """Consequence-based authority rules; observation is broad, irreversible power is narrow."""

    def __init__(self, trusted_principals: Sequence[str] = ("founder", "operator")) -> None:
        self.trusted_principals = tuple(item.casefold() for item in trusted_principals)

    def validate_manifest(self, manifest: SourceAdapterManifest) -> tuple[str, ...]:
        blockers: list[str] = []
        if not manifest.source_id.strip() or not manifest.adapter_id.strip() or not manifest.name.strip():
            blockers.append("source manifest requires source_id, adapter_id, and name")
        if not manifest.capabilities:
            blockers.append("source manifest requires at least one capability")
        if "credential-export" in {item.casefold() for item in manifest.forbidden_capabilities}:
            pass
        elif manifest.requires_credentials:
            blockers.append("credentialed source adapters must explicitly forbid credential-export")
        return tuple(blockers)

    def validate_candidate(self, candidate: OpportunityCandidate, policy: PortfolioPolicy) -> tuple[str, ...]:
        blockers = list(candidate.blockers)
        if len(set(candidate.supporting_source_ids)) < policy.minimum_independent_sources:
            blockers.append(f"portfolio requires at least {policy.minimum_independent_sources} independent sources")
        if candidate.contradicting_claim_ids:
            blockers.append("unresolved contradiction evidence blocks portfolio readiness")
        if candidate.score.evidence_confidence < policy.minimum_evidence_confidence:
            blockers.append("evidence confidence is below portfolio policy")
        if candidate.score.utility_score < policy.minimum_utility_score:
            blockers.append("utility score is below portfolio policy")
        if candidate.expected_upside_usd < 0 or candidate.estimated_cost_usd < 0:
            blockers.append("financial estimates cannot be negative")
        if not candidate.problem_statement.strip() or not candidate.value_proposition.strip():
            blockers.append("candidate requires problem statement and value proposition")
        return tuple(dict.fromkeys(blockers))

    def validate_decision(self, principal: str, reason: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if principal.casefold() not in self.trusted_principals:
            blockers.append("portfolio decision requires a trusted Founder/operator principal")
        if len(reason.strip()) < 12:
            blockers.append("portfolio decision requires a substantive reason")
        return tuple(blockers)

    def validate_mandate(self, mandate: ExperimentMandate) -> tuple[str, ...]:
        blockers = list(self.validate_decision(mandate.principal, mandate.reason))
        if mandate.maximum_cost_usd < 0 or mandate.maximum_external_actions < 0 or mandate.maximum_duration_seconds < 1:
            blockers.append("mandate budgets must be non-negative and duration positive")
        if mandate.autonomy_level == AutonomyLevel.HIGH_CONSEQUENCE:
            blockers.append("high-consequence authority cannot be granted as a reusable experiment mandate")
        if mandate.autonomy_level == AutonomyLevel.SANDBOX_EXPERIMENT and not mandate.reversible_only:
            blockers.append("sandbox experiments must be reversible")
        forbidden = {item.casefold() for item in mandate.forbidden_capabilities}
        if mandate.autonomy_level in {AutonomyLevel.SANDBOX_EXPERIMENT, AutonomyLevel.BOUNDED_EXTERNAL}:
            for required in ("credential-export", "self-approval", "northstar-modification"):
                if required not in forbidden:
                    blockers.append(f"mandate must forbid {required}")
        return tuple(dict.fromkeys(blockers))


class OpportunityIntelligenceEngine:
    engine_id = "aether.opportunity-intelligence"

    def __init__(
        self,
        store: SQLiteOpportunityStore,
        *,
        governor: OpportunityGovernor | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.store = store
        self.governor = governor or OpportunityGovernor()
        self.event_bus = event_bus

    def register_source(self, manifest: SourceAdapterManifest) -> SourceAdapterManifest:
        normalized = replace(manifest, manifest_hash=manifest.manifest_hash or source_manifest_hash(manifest))
        blockers = self.governor.validate_manifest(normalized)
        if blockers:
            raise OpportunityBlocked(blockers)
        saved = self.store.add_manifest(normalized, utc_now())
        self._emit(EventType.OPPORTUNITY_SOURCE_REGISTERED, {
            "source_id": saved.source_id, "adapter_id": saved.adapter_id,
            "kind": saved.kind.value, "capabilities": [item.value for item in saved.capabilities],
            "manifest_hash": saved.manifest_hash,
        })
        return saved

    def record_source_status(self, item: SourceAdapterStatus) -> SourceAdapterStatus:
        normalized = replace(item, checked_at=item.checked_at or utc_now())
        saved = self.store.add_status(normalized)
        self._emit(EventType.OPPORTUNITY_SOURCE_HEALTH_CHECKED, {
            "source_id": saved.source_id, "adapter_id": saved.adapter_id,
            "health": saved.health.value, "reason": saved.reason,
        }, severity="warning" if saved.health.value != "healthy" else "info")
        return saved

    def record_snapshot(self, snapshot: ContentSnapshot) -> ContentSnapshot:
        if not snapshot.content_hash or not snapshot.canonical_url or not snapshot.source_id:
            raise OpportunityBlocked(("snapshot requires source, canonical URL, and content hash",))
        normalized = replace(snapshot, retrieved_at=snapshot.retrieved_at or utc_now())
        saved = self.store.add_snapshot(normalized)
        self._emit(EventType.OPPORTUNITY_SNAPSHOT_RECORDED, {
            "snapshot_id": saved.snapshot_id, "source_id": saved.source_id,
            "canonical_url": saved.canonical_url, "content_hash": saved.content_hash,
            "bytes": len(saved.content_text.encode("utf-8")),
        })
        return saved

    def record_claim(self, claim: ExtractedClaim) -> ExtractedClaim:
        if not claim.statement.strip() or not claim.subject.strip():
            raise OpportunityBlocked(("claim requires statement and subject",))
        if not 0 <= claim.confidence <= 1:
            raise OpportunityBlocked(("claim confidence must be between 0 and 1",))
        self.store.get_snapshot(claim.snapshot_id)
        normalized = replace(claim, observed_at=claim.observed_at or utc_now(), claim_hash=claim.claim_hash or claim_hash(claim))
        saved = self.store.add_claim(normalized)
        self._emit(EventType.OPPORTUNITY_CLAIM_RECORDED, {
            "claim_id": saved.claim_id, "snapshot_id": saved.snapshot_id,
            "source_id": saved.source_id, "subject": saved.subject,
            "stance": saved.stance.value, "claim_hash": saved.claim_hash,
        })
        return saved

    @staticmethod
    def calculate_score(
        *, expected_upside_usd: float, probability_success: float, estimated_cost_usd: float,
        evidence_confidence: float, strategic_alignment: float, reversibility: float,
        time_to_validation: float, legal_risk_penalty: float, platform_dependency_penalty: float,
        saturation_penalty: float,
    ) -> OpportunityScore:
        expected_net = probability_success * expected_upside_usd - estimated_cost_usd
        execution_penalty = min(1.0, estimated_cost_usd / max(expected_upside_usd, 1.0))
        utility = (
            expected_net * max(0.05, evidence_confidence) * max(0.05, strategic_alignment) * max(0.05, reversibility)
            * max(0.05, time_to_validation)
            - estimated_cost_usd * execution_penalty
            - expected_upside_usd * 0.1 * (legal_risk_penalty + platform_dependency_penalty + saturation_penalty)
        )
        return OpportunityScore(
            expected_net_value_usd=round(expected_net, 4), evidence_confidence=round(evidence_confidence, 4),
            strategic_alignment=round(strategic_alignment, 4), reversibility=round(reversibility, 4),
            time_to_validation=round(time_to_validation, 4), execution_cost_penalty=round(execution_penalty, 4),
            legal_risk_penalty=round(legal_risk_penalty, 4), platform_dependency_penalty=round(platform_dependency_penalty, 4),
            saturation_penalty=round(saturation_penalty, 4), utility_score=round(utility, 4),
        )

    def synthesize_candidate(
        self,
        *, title: str, problem_statement: str, beneficiary: str, value_proposition: str,
        revenue_hypothesis: str, category: str, claim_ids: Sequence[str], assumptions: Sequence[str],
        expected_upside_usd: float, probability_success: float, estimated_cost_usd: float,
        estimated_duration_hours: float, risk: str, strategic_alignment: float = 0.7,
        reversibility: float = 0.8, time_to_validation: float = 0.7,
        legal_risk_penalty: float = 0.1, platform_dependency_penalty: float = 0.1,
        saturation_penalty: float = 0.2, strategy_tags: Sequence[str] = (), metadata: Mapping | None = None,
        policy: PortfolioPolicy | None = None,
    ) -> OpportunityCandidate:
        policy = policy or PortfolioPolicy()
        policy.validate()
        claims = [self.store.get_claim(item) for item in claim_ids]
        supporting = [item for item in claims if item.stance == ClaimStance.SUPPORTS]
        contradicting = [item for item in claims if item.stance == ClaimStance.CONTRADICTS]
        independent_sources = tuple(sorted({item.source_id for item in supporting if item.external_reference}))
        if supporting:
            weighted = [item.confidence * _STRENGTH_WEIGHT[item.evidence_strength] for item in supporting]
            evidence_confidence = min(1.0, sum(weighted) / len(weighted) + min(0.2, 0.05 * (len(independent_sources) - 1)))
        else:
            evidence_confidence = 0.0
        score = self.calculate_score(
            expected_upside_usd=expected_upside_usd, probability_success=probability_success,
            estimated_cost_usd=estimated_cost_usd, evidence_confidence=evidence_confidence,
            strategic_alignment=strategic_alignment, reversibility=reversibility,
            time_to_validation=time_to_validation, legal_risk_penalty=legal_risk_penalty,
            platform_dependency_penalty=platform_dependency_penalty, saturation_penalty=saturation_penalty,
        )
        draft = OpportunityCandidate(
            title=title, problem_statement=problem_statement, beneficiary=beneficiary,
            value_proposition=value_proposition, revenue_hypothesis=revenue_hypothesis,
            category=category, claim_ids=tuple(claim_ids), supporting_source_ids=independent_sources,
            contradicting_claim_ids=tuple(item.claim_id for item in contradicting), assumptions=tuple(assumptions),
            score=score, expected_upside_usd=expected_upside_usd, probability_success=probability_success,
            estimated_cost_usd=estimated_cost_usd, estimated_duration_hours=estimated_duration_hours,
            risk=risk, status=OpportunityStatus.OBSERVED, strategy_tags=tuple(strategy_tags),
            metadata=dict(metadata or {}), created_at=utc_now(),
        )
        blockers = self.governor.validate_candidate(draft, policy)
        status = OpportunityStatus.PORTFOLIO_READY if not blockers else OpportunityStatus.EVIDENCE_REQUIRED
        normalized = replace(draft, status=status, blockers=blockers)
        normalized = replace(normalized, candidate_hash=opportunity_candidate_hash(normalized))
        saved = self.store.add_candidate(normalized)
        self._emit(EventType.OPPORTUNITY_CANDIDATE_SYNTHESIZED, {
            "candidate_id": saved.candidate_id, "candidate_hash": saved.candidate_hash,
            "status": saved.status.value, "utility_score": saved.score.utility_score,
            "independent_sources": len(saved.supporting_source_ids), "blockers": list(saved.blockers),
        }, severity="warning" if saved.blockers else "info")
        return saved

    def select_portfolio(self, candidates: Iterable[OpportunityCandidate], policy: PortfolioPolicy | None = None) -> PortfolioSelection:
        policy = policy or PortfolioPolicy()
        policy.validate()
        ready = sorted((item for item in candidates if not self.governor.validate_candidate(item, policy)), key=lambda item: item.score.utility_score, reverse=True)
        selected: list[OpportunityCandidate] = []
        rejected: list[str] = []
        deferred: list[str] = []
        total_budget = 0.0
        category_counts: dict[str, int] = {}
        high_risk = 0
        rationale: list[str] = []
        for candidate in ready:
            if len(selected) >= policy.maximum_selected_candidates:
                deferred.append(candidate.candidate_id)
                continue
            if total_budget + candidate.estimated_cost_usd > policy.maximum_total_experiment_budget_usd:
                deferred.append(candidate.candidate_id)
                rationale.append(f"deferred {candidate.candidate_id}: portfolio budget")
                continue
            proposed_high = high_risk + (1 if candidate.risk.casefold() in {"high", "critical"} else 0)
            if proposed_high > policy.maximum_high_risk_candidates:
                deferred.append(candidate.candidate_id)
                rationale.append(f"deferred {candidate.candidate_id}: high-risk envelope")
                continue
            proposed_count = category_counts.get(candidate.category, 0) + 1
            proposed_total = len(selected) + 1
            if proposed_total > 1 and proposed_count / proposed_total > policy.maximum_single_category_fraction:
                deferred.append(candidate.candidate_id)
                rationale.append(f"deferred {candidate.candidate_id}: category concentration")
                continue
            selected.append(candidate)
            total_budget += candidate.estimated_cost_usd
            high_risk = proposed_high
            category_counts[candidate.category] = proposed_count
        ready_ids = {item.candidate_id for item in ready}
        for item in candidates:
            if item.candidate_id not in ready_ids:
                rejected.append(item.candidate_id)
        selection = PortfolioSelection(
            candidate_ids=tuple(item.candidate_id for item in selected),
            rejected_candidate_ids=tuple(rejected), deferred_candidate_ids=tuple(deferred),
            allocated_budget_usd=round(total_budget, 4), policy_fingerprint=portfolio_policy_fingerprint(policy),
            rationale=tuple(rationale or ("selected by evidence-weighted utility within portfolio envelope",)),
            created_at=utc_now(),
        )
        self._emit(EventType.OPPORTUNITY_PORTFOLIO_SCORED, {
            "selection_id": selection.selection_id, "candidate_ids": list(selection.candidate_ids),
            "deferred_candidate_ids": list(selection.deferred_candidate_ids),
            "rejected_candidate_ids": list(selection.rejected_candidate_ids),
            "allocated_budget_usd": selection.allocated_budget_usd,
        })
        return selection

    def decide(
        self, candidate_id: str, *, decision: PortfolioDecisionType, principal: str,
        reason: str, allocated_budget_usd: float = 0.0, channel: str = "operator",
    ) -> PortfolioDecision:
        candidate = self.store.get_candidate(candidate_id)
        blockers = list(self.governor.validate_decision(principal, reason))
        if decision == PortfolioDecisionType.SELECT:
            blockers.extend(candidate.blockers)
            if allocated_budget_usd < 0 or allocated_budget_usd > max(candidate.estimated_cost_usd, 0.0) * 2 + 1e-9:
                blockers.append("allocated budget must be bounded relative to estimated experiment cost")
        if blockers:
            raise OpportunityBlocked(tuple(dict.fromkeys(blockers)))
        item = PortfolioDecision(
            candidate_id=candidate_id, decision=decision, principal=principal, reason=reason,
            allocated_budget_usd=allocated_budget_usd, channel=channel, decided_at=utc_now(),
        )
        saved = self.store.add_decision(item)
        self._emit(EventType.OPPORTUNITY_PORTFOLIO_DECIDED, {
            "candidate_id": candidate_id, "decision_id": saved.decision_id,
            "decision": saved.decision.value, "principal": principal,
            "allocated_budget_usd": allocated_budget_usd,
        })
        return saved

    def issue_mandate(
        self, candidate_id: str, *, principal: str, autonomy_level: AutonomyLevel,
        allowed_capabilities: Sequence[str], maximum_cost_usd: float,
        maximum_external_actions: int, maximum_duration_seconds: int,
        reason: str, expires_in_seconds: int = 86400,
        reversible_only: bool = True, forbidden_capabilities: Sequence[str] = (
            "credential-export", "self-approval", "northstar-modification", "legal-commitment",
        ),
    ) -> ExperimentMandate:
        decision = self.store.decision(candidate_id)
        if decision is None or decision.decision != PortfolioDecisionType.SELECT:
            raise OpportunityBlocked(("experiment mandate requires a selected portfolio decision",))
        if maximum_cost_usd > decision.allocated_budget_usd + 1e-9:
            raise OpportunityBlocked(("mandate cost exceeds selected portfolio allocation",))
        now = datetime.now(timezone.utc)
        item = ExperimentMandate(
            candidate_id=candidate_id, principal=principal, autonomy_level=autonomy_level,
            allowed_capabilities=tuple(allowed_capabilities), forbidden_capabilities=tuple(forbidden_capabilities),
            maximum_cost_usd=maximum_cost_usd, maximum_external_actions=maximum_external_actions,
            maximum_duration_seconds=maximum_duration_seconds, reversible_only=reversible_only,
            expires_at=(now + timedelta(seconds=expires_in_seconds)).isoformat().replace("+00:00", "Z"),
            reason=reason, status=MandateStatus.ACTIVE, issued_at=utc_now(),
        )
        normalized = replace(item, mandate_hash=mandate_hash(item))
        blockers = self.governor.validate_mandate(normalized)
        if blockers:
            raise OpportunityBlocked(blockers)
        saved = self.store.add_mandate(normalized)
        self._emit(EventType.OPPORTUNITY_MANDATE_ISSUED, {
            "candidate_id": candidate_id, "mandate_id": saved.mandate_id,
            "autonomy_level": saved.autonomy_level.value,
            "maximum_cost_usd": saved.maximum_cost_usd,
            "maximum_external_actions": saved.maximum_external_actions,
        })
        return saved

    def _emit(self, event_type: EventType, payload: dict, severity: str = "info") -> None:
        if self.event_bus:
            self.event_bus.emit(str(event_type.value), actor=self.engine_id, payload=payload, severity=severity)
