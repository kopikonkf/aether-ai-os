"""Evidence-first memory curator and governed knowledge promotion pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any, Iterable, Sequence

from aether.contracts.event_types import EventType
from aether.contracts.knowledge import (
    EvidenceStance,
    KnowledgeDecision,
    KnowledgeDecisionType,
    KnowledgeEvidence,
    KnowledgePromotionBlocked,
    KnowledgeProposal,
    KnowledgeProposalStatus,
    KnowledgeReview,
)
from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.events import EventBus
from aether.memory import AetherMemoryFabric, SQLiteCanonicalMemoryStore
from aether.utils.time import utc_now

from .governance import KnowledgeGovernor
from .projection import ObsidianKnowledgeProjector
from .store import SQLiteKnowledgeProposalStore, normalize_claim


def _tokens(text: str) -> set[str]:
    return {item for item in normalize_claim(text).split() if len(item) > 1}


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _knowledge_content_hash(proposal: KnowledgeProposal, confidence: float) -> str:
    payload = {
        "proposal_id": proposal.proposal_id,
        "claim": proposal.normalized_claim,
        "claim_key": proposal.claim_key,
        "polarity": proposal.polarity,
        "evidence": [
            [item.record_id, item.content_hash, item.stance.value]
            for item in proposal.evidence
        ],
        "confidence": confidence,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class MemoryCurator:
    curator_id = "aether.memory.curator"

    def __init__(
        self,
        canonical: SQLiteCanonicalMemoryStore,
        proposals: SQLiteKnowledgeProposalStore,
        fabric: AetherMemoryFabric,
        *,
        governor: KnowledgeGovernor | None = None,
        event_bus: EventBus | None = None,
        projector: ObsidianKnowledgeProjector | None = None,
    ) -> None:
        self.canonical = canonical
        self.proposals = proposals
        self.fabric = fabric
        self.governor = governor or KnowledgeGovernor()
        self.event_bus = event_bus
        self.projector = projector
        self._decision_lock = asyncio.Lock()

    async def propose(
        self,
        *,
        claim: str,
        evidence_record_ids: Sequence[str],
        claim_key: str | None = None,
        polarity: int = 0,
        contradicting_record_ids: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeProposal:
        support_ids = tuple(dict.fromkeys(str(item) for item in evidence_record_ids if str(item).strip()))
        contradict_ids = tuple(dict.fromkeys(str(item) for item in contradicting_record_ids if str(item).strip()))
        if not support_ids:
            raise ValueError("at least one supporting evidence record is required")
        evidence = await self._evidence_bundle(support_ids, EvidenceStance.SUPPORTS)
        evidence += await self._evidence_bundle(contradict_ids, EvidenceStance.CONTRADICTS)
        normalized = normalize_claim(claim)
        key = normalize_claim(claim_key or claim)
        similar = self.proposals.find_similar(normalized, key)
        duplicate_of = None
        contradiction_proposals: list[str] = []
        for existing in similar:
            if existing.status == KnowledgeProposalStatus.REJECTED:
                continue
            if existing.normalized_claim == normalized or _similarity(existing.claim, claim) >= 0.92:
                duplicate_of = existing.proposal_id
                break
            if key == existing.claim_key and polarity and existing.polarity and polarity == -existing.polarity:
                contradiction_proposals.append(existing.proposal_id)
        proposal = self.proposals.create(
            claim=claim,
            claim_key=key,
            polarity=polarity,
            evidence=evidence,
            duplicate_of=duplicate_of,
            contradiction_ids=tuple(contradiction_proposals),
            metadata=metadata or {},
        )
        self._emit(EventType.KNOWLEDGE_PROPOSED, {
            "proposal_id": proposal.proposal_id,
            "proposal_hash": proposal.proposal_hash,
            "evidence_count": len(proposal.evidence),
            "duplicate_of": proposal.duplicate_of,
            "contradiction_ids": list(proposal.contradiction_ids),
        })
        if proposal.duplicate_of:
            self._emit(EventType.KNOWLEDGE_DUPLICATE_DETECTED, {
                "proposal_id": proposal.proposal_id,
                "duplicate_of": proposal.duplicate_of,
            })
        if proposal.contradiction_ids or contradict_ids:
            self._emit(EventType.KNOWLEDGE_CONTRADICTION_DETECTED, {
                "proposal_id": proposal.proposal_id,
                "proposal_contradictions": list(proposal.contradiction_ids),
                "evidence_contradictions": list(contradict_ids),
            })
        return proposal

    async def curate_explicit_candidates(self, *, limit: int = 500) -> tuple[KnowledgeProposal, ...]:
        """Group only records explicitly marked with ``knowledge_candidate`` metadata."""
        records = await self.canonical.list(limit=limit)
        groups: dict[tuple[str, int, str], list[str]] = {}
        claims: dict[tuple[str, int, str], str] = {}
        for record in records:
            candidate = record.metadata.get("knowledge_candidate") if record.metadata else None
            if not isinstance(candidate, dict):
                continue
            claim = str(candidate.get("claim") or "").strip()
            if not claim:
                continue
            key = normalize_claim(str(candidate.get("claim_key") or claim))
            polarity = int(candidate.get("polarity", 0))
            group_key = (key, polarity, normalize_claim(claim))
            groups.setdefault(group_key, []).append(str(record.record_id))
            claims[group_key] = claim
        created: list[KnowledgeProposal] = []
        minimum = self.governor.policy.minimum_supporting_evidence
        for (key, polarity, _normalized), record_ids in groups.items():
            if len(set(record_ids)) < minimum:
                continue
            proposal = await self.propose(
                claim=claims[(key, polarity, _normalized)],
                claim_key=key,
                polarity=polarity,
                evidence_record_ids=tuple(dict.fromkeys(record_ids)),
                metadata={"candidate_source": "explicit-canonical-metadata"},
            )
            created.append(proposal)
        self._emit(EventType.KNOWLEDGE_CURATOR_COMPLETED, {
            "candidate_groups": len(groups),
            "proposal_count": len(created),
        })
        return tuple(created)

    def review(self, proposal_id: str) -> KnowledgeReview:
        proposal = self.proposals.get(proposal_id)
        review = self.governor.review(proposal)
        decision = self.proposals.get_decision(proposal_id)
        return KnowledgeReview(
            proposal=proposal,
            decision=decision,
            blockers=review.blockers,
            warnings=review.warnings,
        )

    async def decide(
        self,
        proposal_id: str,
        *,
        approved: bool,
        principal: str,
        channel: str,
        reason: str,
        confidence: float | None = None,
        project: bool = True,
    ) -> KnowledgeReview:
        # Single-node serialization prevents approve/reject races across the
        # canonical and proposal SQLite stores. Multi-node consensus remains a
        # future boundary.
        async with self._decision_lock:
            return await self._decide_locked(
                proposal_id,
                approved=approved,
                principal=principal,
                channel=channel,
                reason=reason,
                confidence=confidence,
                project=project,
            )

    async def _decide_locked(
        self,
        proposal_id: str,
        *,
        approved: bool,
        principal: str,
        channel: str,
        reason: str,
        confidence: float | None = None,
        project: bool = True,
    ) -> KnowledgeReview:
        proposal = self.proposals.get(proposal_id)
        existing = self.proposals.get_decision(proposal_id)
        if existing is not None:
            requested = KnowledgeDecisionType.APPROVE if approved else KnowledgeDecisionType.REJECT
            if existing.decision != requested:
                from aether.contracts.knowledge import KnowledgeDecisionConflict
                raise KnowledgeDecisionConflict(
                    f"proposal {proposal_id} already has terminal decision {existing.decision.value}"
                )
            return KnowledgeReview(proposal=self.proposals.get(proposal_id), decision=existing)
        decision_blockers = self.governor.validate_decision(
            principal=principal, reason=reason, confidence=confidence,
        )
        if decision_blockers:
            raise KnowledgePromotionBlocked(decision_blockers)
        if not approved:
            decision = self.proposals.decide(
                proposal_id,
                decision=KnowledgeDecisionType.REJECT,
                principal=principal,
                channel=channel,
                reason=reason,
            )
            self._emit(EventType.KNOWLEDGE_REJECTED, asdict(decision))
            return KnowledgeReview(proposal=self.proposals.get(proposal_id), decision=decision)

        review = self.governor.review(proposal)
        if review.blockers:
            raise KnowledgePromotionBlocked(review.blockers)
        effective_confidence = confidence if confidence is not None else min(
            self.governor.policy.maximum_confidence,
            0.50 + 0.10 * len([item for item in proposal.evidence if item.stance == EvidenceStance.SUPPORTS]),
        )
        record = await self._promote_record(proposal, effective_confidence, principal, channel, reason)
        decision = self.proposals.decide(
            proposal_id,
            decision=KnowledgeDecisionType.APPROVE,
            principal=principal,
            channel=channel,
            reason=reason,
            confidence=effective_confidence,
            knowledge_record_id=record.record_id,
        )
        self._emit(EventType.KNOWLEDGE_PROMOTED, {
            "proposal_id": proposal_id,
            "decision_id": decision.decision_id,
            "knowledge_record_id": record.record_id,
            "principal": principal,
            "confidence": effective_confidence,
        })
        if project and self.projector is not None:
            path = await self.projector.project(self.proposals.get(proposal_id), decision, record)
            self._emit(EventType.KNOWLEDGE_PROJECTED, {
                "proposal_id": proposal_id,
                "knowledge_record_id": record.record_id,
                "path": str(path),
                "authority": "projection_only",
            })
        return KnowledgeReview(proposal=self.proposals.get(proposal_id), decision=decision)

    async def project(self, proposal_id: str) -> str | None:
        if self.projector is None:
            return None
        proposal = self.proposals.get(proposal_id)
        decision = self.proposals.get_decision(proposal_id)
        if decision is None or decision.decision != KnowledgeDecisionType.APPROVE or not decision.knowledge_record_id:
            raise KnowledgePromotionBlocked(("only promoted knowledge can be projected",))
        record = await self.canonical.get(decision.knowledge_record_id)
        if record is None:
            raise RuntimeError("promoted knowledge record is missing")
        return str(await self.projector.project(proposal, decision, record))

    async def _evidence_bundle(
        self, record_ids: Iterable[str], stance: EvidenceStance,
    ) -> tuple[KnowledgeEvidence, ...]:
        result: list[KnowledgeEvidence] = []
        for record_id in record_ids:
            record = await self.canonical.get(record_id)
            if record is None:
                raise ValueError(f"canonical evidence record not found: {record_id}")
            if not record.content_hash:
                raise ValueError(f"canonical evidence lacks content hash: {record_id}")
            provenance = record.provenance
            result.append(KnowledgeEvidence(
                record_id=str(record.record_id),
                content_hash=record.content_hash,
                stance=stance,
                source=provenance.source if provenance else "unknown",
                observed_at=(provenance.observed_at if provenance else record.created_at) or "unknown",
                excerpt=record.content[:1200],
                session_id=provenance.session_id if provenance else None,
                correlation_id=provenance.correlation_id if provenance else None,
            ))
        return tuple(result)

    async def _promote_record(
        self,
        proposal: KnowledgeProposal,
        confidence: float,
        principal: str,
        channel: str,
        reason: str,
    ) -> MemoryRecord:
        content_hash = _knowledge_content_hash(proposal, confidence)
        record = MemoryRecord(
            key=f"knowledge:{proposal.claim_key}",
            value={
                "claim": proposal.claim,
                "claim_key": proposal.claim_key,
                "polarity": proposal.polarity,
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal.proposal_hash,
                "confidence": confidence,
                "evidence": [asdict(item) for item in proposal.evidence],
                "governance": {
                    "principal": principal,
                    "channel": channel,
                    "reason": reason,
                },
            },
            namespace="knowledge",
            kind=MemoryKind.KNOWLEDGE,
            content=proposal.claim,
            metadata={
                "proposal_id": proposal.proposal_id,
                "claim_key": proposal.claim_key,
                "polarity": proposal.polarity,
                "confidence": confidence,
                "governance_required": True,
                "belief": False,
            },
            record_id=f"knowledge.{proposal.proposal_id}",
            content_hash=content_hash,
            created_at=proposal.created_at,
            provenance=MemoryProvenance(
                source="trusted-knowledge-governance",
                observed_at=proposal.created_at,
                evidence_links=tuple(item.record_id for item in proposal.evidence),
            ),
        )
        return await self.fabric.remember(record)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type=event_type, actor=self.curator_id, payload=payload)
