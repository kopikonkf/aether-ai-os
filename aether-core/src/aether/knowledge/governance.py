"""Governance rules for evidence-backed knowledge promotion."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from aether.contracts.knowledge import EvidenceStance, KnowledgeProposal, KnowledgeReview


@dataclass(frozen=True)
class KnowledgePromotionPolicy:
    minimum_supporting_evidence: int = 2
    minimum_distinct_sources: int = 2
    maximum_confidence: float = 0.90
    duplicate_proposals_blocked: bool = True
    unresolved_contradictions_blocked: bool = True
    require_trusted_principal: bool = True
    require_decision_reason: bool = True

    @classmethod
    def load(cls, path: Path | None = None) -> "KnowledgePromotionPolicy":
        target = path or Path(str(files("aether.knowledge").joinpath("knowledge_promotion.yaml")))
        raw: dict[str, Any] = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        promotion = raw.get("promotion") or {}
        return cls(
            minimum_supporting_evidence=int(promotion.get("minimum_supporting_evidence", 2)),
            minimum_distinct_sources=int(promotion.get("minimum_distinct_sources", 2)),
            maximum_confidence=float(promotion.get("maximum_confidence", 0.90)),
            duplicate_proposals_blocked=promotion.get("duplicate_proposals") == "blocked",
            unresolved_contradictions_blocked=promotion.get("unresolved_contradictions") == "blocked",
            require_trusted_principal=bool(promotion.get("require_trusted_principal", True)),
            require_decision_reason=bool(promotion.get("require_decision_reason", True)),
        )


class KnowledgeGovernor:
    governor_id = "aether.governance.knowledge"

    def __init__(self, policy: KnowledgePromotionPolicy | None = None) -> None:
        self.policy = policy or KnowledgePromotionPolicy.load()

    def review(self, proposal: KnowledgeProposal) -> KnowledgeReview:
        supporting = tuple(item for item in proposal.evidence if item.stance == EvidenceStance.SUPPORTS)
        sources = {item.source for item in supporting if item.source.strip()}
        blockers: list[str] = []
        warnings: list[str] = []
        if len(supporting) < self.policy.minimum_supporting_evidence:
            blockers.append(
                f"requires at least {self.policy.minimum_supporting_evidence} supporting evidence records"
            )
        if len(sources) < self.policy.minimum_distinct_sources:
            blockers.append(
                f"requires at least {self.policy.minimum_distinct_sources} distinct evidence sources"
            )
        if self.policy.duplicate_proposals_blocked and proposal.duplicate_of:
            blockers.append(f"duplicate of proposal {proposal.duplicate_of}")
        if self.policy.unresolved_contradictions_blocked and proposal.contradiction_ids:
            blockers.append(
                "unresolved contradictions: " + ", ".join(proposal.contradiction_ids)
            )
        if any(item.stance == EvidenceStance.CONTRADICTS for item in proposal.evidence):
            warnings.append("proposal evidence bundle contains contradicting evidence")
        return KnowledgeReview(proposal=proposal, decision=None, blockers=tuple(blockers), warnings=tuple(warnings))

    def validate_decision(self, *, principal: str, reason: str, confidence: float | None) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.policy.require_trusted_principal and not principal.strip():
            blockers.append("trusted principal is required")
        if self.policy.require_decision_reason and not reason.strip():
            blockers.append("decision reason is required")
        if confidence is not None:
            if not 0.0 <= confidence <= self.policy.maximum_confidence:
                blockers.append(
                    f"confidence must be between 0 and {self.policy.maximum_confidence:.2f}"
                )
        return tuple(blockers)
