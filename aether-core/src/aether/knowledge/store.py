"""Append-only SQLite store for knowledge proposals, evidence, and decisions."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable

from aether.contracts.knowledge import (
    EvidenceStance,
    KnowledgeDecision,
    KnowledgeDecisionConflict,
    KnowledgeDecisionType,
    KnowledgeEvidence,
    KnowledgeProposal,
    KnowledgeProposalNotFound,
    KnowledgeProposalStatus,
)
from aether.utils.ids import new_id
from aether.utils.time import utc_now

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s-]+", re.UNICODE)


def normalize_claim(claim: str) -> str:
    value = _PUNCT.sub(" ", claim.casefold().strip())
    return _SPACE.sub(" ", value).strip()


def canonical_proposal_hash(
    *,
    claim: str,
    claim_key: str,
    polarity: int,
    evidence: Iterable[KnowledgeEvidence],
) -> str:
    payload = {
        "claim": normalize_claim(claim),
        "claim_key": claim_key.strip().casefold(),
        "polarity": int(polarity),
        "evidence": [
            {
                "record_id": item.record_id,
                "content_hash": item.content_hash,
                "stance": item.stance.value,
            }
            for item in sorted(evidence, key=lambda item: (item.record_id, item.stance.value))
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SQLiteKnowledgeProposalStore:
    """Proposal state is derived from immutable proposal and decision records."""

    store_id = "aether.knowledge.proposals.sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    claim TEXT NOT NULL,
                    normalized_claim TEXT NOT NULL,
                    claim_key TEXT NOT NULL,
                    polarity INTEGER NOT NULL,
                    duplicate_of TEXT,
                    contradiction_ids_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    proposal_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_claim
                    ON knowledge_proposals(normalized_claim);
                CREATE INDEX IF NOT EXISTS idx_knowledge_key
                    ON knowledge_proposals(claim_key, polarity);

                CREATE TABLE IF NOT EXISTS knowledge_evidence (
                    proposal_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    stance TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    session_id TEXT,
                    correlation_id TEXT,
                    PRIMARY KEY(proposal_id, record_id, stance),
                    FOREIGN KEY(proposal_id) REFERENCES knowledge_proposals(proposal_id)
                );

                CREATE TABLE IF NOT EXISTS knowledge_decisions (
                    decision_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE,
                    decision TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    confidence REAL,
                    knowledge_record_id TEXT,
                    decided_at TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES knowledge_proposals(proposal_id)
                );

                CREATE TRIGGER IF NOT EXISTS knowledge_proposals_no_update
                BEFORE UPDATE ON knowledge_proposals BEGIN
                    SELECT RAISE(ABORT, 'knowledge proposals are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_proposals_no_delete
                BEFORE DELETE ON knowledge_proposals BEGIN
                    SELECT RAISE(ABORT, 'knowledge proposals are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_evidence_no_update
                BEFORE UPDATE ON knowledge_evidence BEGIN
                    SELECT RAISE(ABORT, 'knowledge evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_evidence_no_delete
                BEFORE DELETE ON knowledge_evidence BEGIN
                    SELECT RAISE(ABORT, 'knowledge evidence is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_decisions_no_update
                BEFORE UPDATE ON knowledge_decisions BEGIN
                    SELECT RAISE(ABORT, 'knowledge decisions are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_decisions_no_delete
                BEFORE DELETE ON knowledge_decisions BEGIN
                    SELECT RAISE(ABORT, 'knowledge decisions are immutable');
                END;
                """
            )

    def create(
        self,
        *,
        claim: str,
        claim_key: str,
        polarity: int,
        evidence: tuple[KnowledgeEvidence, ...],
        duplicate_of: str | None = None,
        contradiction_ids: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
        proposal_id: str | None = None,
        created_at: str | None = None,
    ) -> KnowledgeProposal:
        normalized = normalize_claim(claim)
        if not normalized:
            raise ValueError("knowledge claim must not be empty")
        if polarity not in {-1, 0, 1}:
            raise ValueError("polarity must be -1, 0, or 1")
        if not evidence:
            raise ValueError("knowledge proposal requires evidence")
        key = claim_key.strip().casefold() or normalized
        proposal_hash = canonical_proposal_hash(
            claim=claim, claim_key=key, polarity=polarity, evidence=evidence,
        )
        existing = self.by_hash(proposal_hash)
        if existing is not None:
            return existing
        proposal_id = proposal_id or new_id("kprop")
        created_at = created_at or utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO knowledge_proposals(
                    proposal_id, claim, normalized_claim, claim_key, polarity,
                    duplicate_of, contradiction_ids_json, metadata_json,
                    created_at, proposal_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposal_id, claim.strip(), normalized, key, polarity,
                    duplicate_of, json.dumps(sorted(set(contradiction_ids))),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, default=str),
                    created_at, proposal_hash,
                ),
            )
            conn.executemany(
                """INSERT INTO knowledge_evidence(
                    proposal_id, record_id, content_hash, stance, source,
                    observed_at, excerpt, session_id, correlation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        proposal_id, item.record_id, item.content_hash,
                        item.stance.value, item.source, item.observed_at,
                        item.excerpt, item.session_id, item.correlation_id,
                    )
                    for item in evidence
                ],
            )
        return self.get(proposal_id)

    def decide(
        self,
        proposal_id: str,
        *,
        decision: KnowledgeDecisionType,
        principal: str,
        channel: str,
        reason: str,
        confidence: float | None = None,
        knowledge_record_id: str | None = None,
        decision_id: str | None = None,
    ) -> KnowledgeDecision:
        self.get(proposal_id)
        existing = self.get_decision(proposal_id)
        if existing is not None:
            if existing.decision == decision:
                return existing
            raise KnowledgeDecisionConflict(
                f"proposal {proposal_id} already has terminal decision {existing.decision.value}"
            )
        if not principal.strip() or not reason.strip():
            raise ValueError("principal and reason are required")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        item = KnowledgeDecision(
            decision_id=decision_id or new_id("kdec"),
            proposal_id=proposal_id,
            decision=decision,
            principal=principal.strip(),
            channel=channel.strip() or "unknown",
            reason=reason.strip(),
            confidence=confidence,
            knowledge_record_id=knowledge_record_id,
            decided_at=utc_now(),
        )
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO knowledge_decisions(
                        decision_id, proposal_id, decision, principal, channel,
                        reason, confidence, knowledge_record_id, decided_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.decision_id, item.proposal_id, item.decision.value,
                        item.principal, item.channel, item.reason, item.confidence,
                        item.knowledge_record_id, item.decided_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = self.get_decision(proposal_id)
                if existing is not None:
                    if existing.decision == decision:
                        return existing
                    raise KnowledgeDecisionConflict(
                        f"proposal {proposal_id} already has terminal decision {existing.decision.value}"
                    ) from exc
                raise
        return item

    def get(self, proposal_id: str) -> KnowledgeProposal:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise KnowledgeProposalNotFound(proposal_id)
        return self._row_to_proposal(row)

    def by_hash(self, proposal_hash: str) -> KnowledgeProposal | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_proposals WHERE proposal_hash = ?", (proposal_hash,)
            ).fetchone()
        return self._row_to_proposal(row) if row else None

    def list(self, status: KnowledgeProposalStatus | None = None, limit: int = 200) -> tuple[KnowledgeProposal, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        items = tuple(self._row_to_proposal(row) for row in rows)
        return tuple(item for item in items if status is None or item.status == status)

    def find_similar(self, normalized_claim: str, claim_key: str) -> tuple[KnowledgeProposal, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM knowledge_proposals
                   WHERE normalized_claim = ? OR claim_key = ?
                   ORDER BY created_at DESC""",
                (normalized_claim, claim_key),
            ).fetchall()
        return tuple(self._row_to_proposal(row) for row in rows)

    def get_decision(self, proposal_id: str) -> KnowledgeDecision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_decisions WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            return None
        return KnowledgeDecision(
            decision_id=row["decision_id"],
            proposal_id=row["proposal_id"],
            decision=KnowledgeDecisionType(row["decision"]),
            principal=row["principal"],
            channel=row["channel"],
            reason=row["reason"],
            confidence=row["confidence"],
            knowledge_record_id=row["knowledge_record_id"],
            decided_at=row["decided_at"],
        )

    def _evidence(self, proposal_id: str) -> tuple[KnowledgeEvidence, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM knowledge_evidence
                   WHERE proposal_id = ? ORDER BY stance, record_id""",
                (proposal_id,),
            ).fetchall()
        return tuple(
            KnowledgeEvidence(
                record_id=row["record_id"],
                content_hash=row["content_hash"],
                stance=EvidenceStance(row["stance"]),
                source=row["source"],
                observed_at=row["observed_at"],
                excerpt=row["excerpt"],
                session_id=row["session_id"],
                correlation_id=row["correlation_id"],
            )
            for row in rows
        )

    def _row_to_proposal(self, row: sqlite3.Row) -> KnowledgeProposal:
        decision = self.get_decision(row["proposal_id"])
        status = KnowledgeProposalStatus.PROPOSED
        decision_id = None
        knowledge_record_id = None
        if decision is not None:
            decision_id = decision.decision_id
            knowledge_record_id = decision.knowledge_record_id
            status = (
                KnowledgeProposalStatus.PROMOTED
                if decision.decision == KnowledgeDecisionType.APPROVE
                else KnowledgeProposalStatus.REJECTED
            )
        return KnowledgeProposal(
            proposal_id=row["proposal_id"],
            claim=row["claim"],
            normalized_claim=row["normalized_claim"],
            claim_key=row["claim_key"],
            polarity=int(row["polarity"]),
            evidence=self._evidence(row["proposal_id"]),
            duplicate_of=row["duplicate_of"],
            contradiction_ids=tuple(json.loads(row["contradiction_ids_json"])),
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            proposal_hash=row["proposal_hash"],
            status=status,
            decision_id=decision_id,
            knowledge_record_id=knowledge_record_id,
        )
