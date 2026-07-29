from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from aether.contracts import (
    KnowledgeDecisionConflict,
    KnowledgePromotionBlocked,
    KnowledgeProposalStatus,
    MemoryKind,
    MemoryProvenance,
    MemoryQuery,
    MemoryRecord,
)
from aether.events import EventBus
from aether.knowledge import (
    MemoryCurator,
    ObsidianKnowledgeProjector,
    SQLiteKnowledgeProposalStore,
)
from aether.memory import AetherMemoryFabric, SQLiteCanonicalMemoryStore, SQLiteLexicalMemoryProvider


def _system(tmp_path: Path):
    canonical = SQLiteCanonicalMemoryStore(tmp_path / "canonical.sqlite3")
    retrieval = SQLiteLexicalMemoryProvider(tmp_path / "index.sqlite3", canonical)
    fabric = AetherMemoryFabric(canonical, retrieval, event_bus=EventBus(tmp_path / "memory.jsonl"))
    proposals = SQLiteKnowledgeProposalStore(tmp_path / "knowledge.sqlite3")
    curator = MemoryCurator(
        canonical,
        proposals,
        fabric,
        event_bus=EventBus(tmp_path / "knowledge-events.jsonl"),
        projector=ObsidianKnowledgeProjector(tmp_path / "vault"),
    )
    return canonical, retrieval, fabric, proposals, curator


async def _evidence(fabric, *, key: str, text: str, source: str, claim: str | None = None, claim_key: str | None = None, polarity: int = 1):
    metadata = {}
    if claim:
        metadata["knowledge_candidate"] = {
            "claim": claim,
            "claim_key": claim_key or claim,
            "polarity": polarity,
        }
    return await fabric.remember(MemoryRecord(
        key=key,
        value=text,
        namespace="episodes",
        kind=MemoryKind.OBSERVATION,
        content=text,
        metadata=metadata,
        provenance=MemoryProvenance(source, f"2026-07-28T00:00:0{key[-1]}Z"),
    ))


def test_direct_knowledge_and_belief_writes_are_blocked(tmp_path: Path) -> None:
    _canonical, _retrieval, fabric, _proposals, _curator = _system(tmp_path)

    async def scenario():
        with pytest.raises(PermissionError, match="direct knowledge writes"):
            await fabric.remember(MemoryRecord(
                key="bypass",
                value="bypass",
                namespace="knowledge",
                kind=MemoryKind.KNOWLEDGE,
                content="This must not bypass governance.",
                provenance=MemoryProvenance("model", "2026-07-28T00:00:00Z"),
            ))
        with pytest.raises(PermissionError, match="belief writes"):
            await fabric.remember(MemoryRecord(
                key="belief-bypass",
                value="belief",
                namespace="beliefs",
                kind=MemoryKind.BELIEF,
                content="Conversation is now belief.",
                provenance=MemoryProvenance("conversation", "2026-07-28T00:00:00Z"),
            ))

    asyncio.run(scenario())


def test_evidence_bundle_governance_promotes_knowledge_and_projects(tmp_path: Path) -> None:
    canonical, _retrieval, fabric, proposals, curator = _system(tmp_path)

    async def scenario():
        one = await _evidence(fabric, key="e1", text="Adapter A was replaced without changing Core.", source="runtime:test-a")
        two = await _evidence(fabric, key="e2", text="Adapter B was replaced without changing Core.", source="runtime:test-b")
        proposal = await curator.propose(
            claim="Aether runtime adapters are replaceable without changing Core.",
            claim_key="architecture.runtime-adapter-replaceability",
            polarity=1,
            evidence_record_ids=[one.record_id, two.record_id],
        )
        review = curator.review(proposal.proposal_id)
        promoted = await curator.decide(
            proposal.proposal_id,
            approved=True,
            principal="founder",
            channel="http",
            reason="Two independent runtime replacement tests passed.",
            confidence=0.80,
        )
        context = await fabric.retrieve(MemoryQuery(
            "runtime adapters replaceable", namespaces=("knowledge",), limit=5,
        ))
        record = await canonical.get(promoted.proposal.knowledge_record_id)
        path = await curator.project(proposal.proposal_id)
        return proposal, review, promoted, context, record, Path(path)

    proposal, review, promoted, context, record, path = asyncio.run(scenario())
    assert proposal.status == KnowledgeProposalStatus.PROPOSED
    assert review.blockers == ()
    assert promoted.proposal.status == KnowledgeProposalStatus.PROMOTED
    assert promoted.decision.principal == "founder"
    assert record.kind == MemoryKind.KNOWLEDGE
    assert record.metadata["belief"] is False
    assert set(record.provenance.evidence_links) == {item.record_id for item in proposal.evidence}
    assert context.hits[0].record.record_id == record.record_id
    text = path.read_text(encoding="utf-8")
    assert "authority: projection_only" in text
    assert "Two independent runtime replacement tests passed" in text
    assert proposals.get_decision(proposal.proposal_id).decision.value == "approve"


def test_duplicate_and_contradiction_are_visible_and_block_approval(tmp_path: Path) -> None:
    _canonical, _retrieval, fabric, _proposals, curator = _system(tmp_path)

    async def scenario():
        a = await _evidence(fabric, key="e1", text="Test one supports modular adapters.", source="source:a")
        b = await _evidence(fabric, key="e2", text="Test two supports modular adapters.", source="source:b")
        first = await curator.propose(
            claim="Runtime adapters remain replaceable.",
            claim_key="runtime.replaceable",
            polarity=1,
            evidence_record_ids=[a.record_id, b.record_id],
        )
        await curator.decide(
            first.proposal_id,
            approved=True,
            principal="founder",
            channel="test",
            reason="Independent evidence verified.",
            confidence=0.75,
        )
        duplicate = await curator.propose(
            claim="Runtime adapters remain replaceable.",
            claim_key="runtime.replaceable",
            polarity=1,
            evidence_record_ids=[a.record_id, b.record_id],
            metadata={"attempt": "duplicate"},
        )
        opposing = await curator.propose(
            claim="Runtime adapters must not be replaceable.",
            claim_key="runtime.replaceable",
            polarity=-1,
            evidence_record_ids=[a.record_id, b.record_id],
        )
        return first, duplicate, opposing

    first, duplicate, opposing = asyncio.run(scenario())
    assert duplicate.proposal_id == first.proposal_id  # identical evidence bundle is idempotent

    async def make_nonidentical_duplicate():
        c = await _evidence(fabric, key="e3", text="A third test supports modular adapters.", source="source:c")
        d = await _evidence(fabric, key="e4", text="A fourth test supports modular adapters.", source="source:d")
        return await curator.propose(
            claim="Runtime adapters remain replaceable.",
            claim_key="runtime.replaceable",
            polarity=1,
            evidence_record_ids=[c.record_id, d.record_id],
        )

    duplicate2 = asyncio.run(make_nonidentical_duplicate())
    assert duplicate2.duplicate_of == first.proposal_id
    with pytest.raises(KnowledgePromotionBlocked, match="duplicate"):
        asyncio.run(curator.decide(
            duplicate2.proposal_id,
            approved=True,
            principal="founder",
            channel="test",
            reason="Should be blocked.",
            confidence=0.7,
        ))
    assert first.proposal_id in opposing.contradiction_ids
    with pytest.raises(KnowledgePromotionBlocked, match="contradictions"):
        asyncio.run(curator.decide(
            opposing.proposal_id,
            approved=True,
            principal="founder",
            channel="test",
            reason="Should remain unresolved.",
            confidence=0.7,
        ))


def test_explicit_candidate_scan_never_curates_unmarked_conversation(tmp_path: Path) -> None:
    _canonical, _retrieval, fabric, _proposals, curator = _system(tmp_path)
    claim = "Northstar has exactly one authority file."

    async def scenario():
        await _evidence(fabric, key="e0", text="Casual user message repeating the claim.", source="conversation")
        await _evidence(fabric, key="e1", text="Authority test found one Northstar.", source="test:a", claim=claim, claim_key="northstar.single")
        first_scan = await curator.curate_explicit_candidates()
        await _evidence(fabric, key="e2", text="Packaging test found one Northstar.", source="test:b", claim=claim, claim_key="northstar.single")
        second_scan = await curator.curate_explicit_candidates()
        return first_scan, second_scan

    first_scan, second_scan = asyncio.run(scenario())
    assert first_scan == ()
    assert len(second_scan) == 1
    assert len(second_scan[0].evidence) == 2
    assert {item.source for item in second_scan[0].evidence} == {"test:a", "test:b"}


def test_decision_and_evidence_tables_are_immutable(tmp_path: Path) -> None:
    _canonical, _retrieval, fabric, proposals, curator = _system(tmp_path)

    async def scenario():
        one = await _evidence(fabric, key="e1", text="Evidence one.", source="a")
        two = await _evidence(fabric, key="e2", text="Evidence two.", source="b")
        proposal = await curator.propose(
            claim="A governed claim.", claim_key="governed.claim", polarity=1,
            evidence_record_ids=[one.record_id, two.record_id],
        )
        await curator.decide(
            proposal.proposal_id, approved=False, principal="founder", channel="test",
            reason="Evidence is insufficient in substance.",
        )
        return proposal

    proposal = asyncio.run(scenario())
    with pytest.raises(KnowledgeDecisionConflict):
        proposals.decide(
            proposal.proposal_id,
            decision=__import__("aether.contracts", fromlist=["KnowledgeDecisionType"]).KnowledgeDecisionType.APPROVE,
            principal="founder",
            channel="test",
            reason="Contradictory late decision.",
        )
    with sqlite3.connect(proposals.path) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("UPDATE knowledge_proposals SET claim='tampered' WHERE proposal_id=?", (proposal.proposal_id,))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            conn.execute("DELETE FROM knowledge_decisions WHERE proposal_id=?", (proposal.proposal_id,))
