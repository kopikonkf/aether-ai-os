"""Provider-neutral knowledge curation and promotion contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class KnowledgeProposalStatus(StrEnum):
    PROPOSED = "proposed"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class KnowledgeDecisionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True)
class KnowledgeEvidence:
    record_id: str
    content_hash: str
    stance: EvidenceStance
    source: str
    observed_at: str
    excerpt: str
    session_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class KnowledgeProposal:
    proposal_id: str
    claim: str
    normalized_claim: str
    claim_key: str
    polarity: int
    evidence: tuple[KnowledgeEvidence, ...]
    duplicate_of: str | None = None
    contradiction_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    proposal_hash: str = ""
    status: KnowledgeProposalStatus = KnowledgeProposalStatus.PROPOSED
    decision_id: str | None = None
    knowledge_record_id: str | None = None


@dataclass(frozen=True)
class KnowledgeDecision:
    decision_id: str
    proposal_id: str
    decision: KnowledgeDecisionType
    principal: str
    channel: str
    reason: str
    decided_at: str
    confidence: float | None = None
    knowledge_record_id: str | None = None


@dataclass(frozen=True)
class KnowledgeReview:
    proposal: KnowledgeProposal
    decision: KnowledgeDecision | None
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


class KnowledgePromotionError(RuntimeError):
    """Base error for governed knowledge promotion."""


class KnowledgeProposalNotFound(KnowledgePromotionError):
    pass


class KnowledgeDecisionConflict(KnowledgePromotionError):
    pass


class KnowledgePromotionBlocked(KnowledgePromotionError):
    def __init__(self, blockers: tuple[str, ...]):
        self.blockers = blockers
        super().__init__("knowledge promotion blocked: " + "; ".join(blockers))
