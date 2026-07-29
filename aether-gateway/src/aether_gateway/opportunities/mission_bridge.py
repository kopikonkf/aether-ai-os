"""Convert selected opportunities into mission briefs without bypassing mission review."""
from __future__ import annotations

from aether.contracts.missions import MissionLane, MissionRisk, OpportunityEvidence, OpportunityEvidenceStance
from aether.contracts.opportunities import OpportunityBlocked, PortfolioDecisionType
from aether.missions import MissionOrchestrator
from aether.opportunities import OpportunityIntelligenceEngine


class OpportunityMissionBridge:
    bridge_id = "aether.opportunity-mission-bridge"

    def __init__(self, intelligence: OpportunityIntelligenceEngine, missions: MissionOrchestrator) -> None:
        self.intelligence = intelligence
        self.missions = missions

    def convert(self, candidate_id: str):
        candidate = self.intelligence.store.get_candidate(candidate_id)
        decision = self.intelligence.store.decision(candidate_id)
        if decision is None or decision.decision != PortfolioDecisionType.SELECT:
            raise OpportunityBlocked(("mission conversion requires a trusted selected portfolio decision",))
        evidence = []
        for claim_id in candidate.claim_ids:
            claim = self.intelligence.store.get_claim(claim_id)
            evidence.append(OpportunityEvidence(
                source=claim.source_id, independent_source_id=claim.source_id,
                statement=claim.statement,
                stance=OpportunityEvidenceStance.CONTRADICTS if claim.stance.value == "contradicts" else OpportunityEvidenceStance.SUPPORTS,
                observed_at=claim.observed_at, external_reference=claim.external_reference,
                verified=claim.evidence_strength.value == "verified",
                metadata={"claim_id": claim.claim_id, "snapshot_id": claim.snapshot_id, "opportunity_candidate_id": candidate_id},
            ))
        brief = self.missions.intake_opportunity(
            title=candidate.title, lane=MissionLane.EXTERNAL_VALUE,
            problem_statement=candidate.problem_statement, beneficiary=candidate.beneficiary,
            value_proposition=candidate.value_proposition, probability_success=candidate.probability_success,
            upside_usd=candidate.expected_upside_usd, estimated_cost_usd=candidate.estimated_cost_usd,
            estimated_duration_hours=candidate.estimated_duration_hours, revenue_hypothesis=candidate.revenue_hypothesis,
            assumptions=candidate.assumptions, evidence=evidence,
            risk=MissionRisk(candidate.risk if candidate.risk in {"low", "medium", "high", "critical"} else "medium"),
            confidence=candidate.score.evidence_confidence,
            metadata={
                "opportunity_candidate_id": candidate_id, "portfolio_decision_id": decision.decision_id,
                "portfolio_allocation_usd": decision.allocated_budget_usd,
                "candidate_hash": candidate.candidate_hash,
            },
        )
        return brief
