"""Durable append-only evidence, candidate, decision, and mandate ledger."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from aether.contracts.opportunities import (
    ContentSnapshot, ExperimentMandate, ExtractedClaim, OpportunityCandidate, OpportunityNotFound,
    PortfolioDecision, PortfolioDecisionConflict, PortfolioDecisionType, ScoutRunReceipt,
    SourceAdapterManifest, SourceAdapterStatus, content_snapshot_from_payload, content_snapshot_payload,
    experiment_mandate_from_payload, experiment_mandate_payload, extracted_claim_from_payload,
    extracted_claim_payload, opportunity_candidate_from_payload, opportunity_candidate_payload,
    source_manifest_from_payload, source_manifest_payload,
)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str) -> Any:
    return json.loads(value)


class SQLiteOpportunityStore:
    store_id = "aether.opportunities.sqlite"

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
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS source_manifests (
                adapter_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_status (
                status_id INTEGER PRIMARY KEY AUTOINCREMENT, adapter_id TEXT NOT NULL, health TEXT NOT NULL,
                payload_json TEXT NOT NULL, checked_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS content_snapshots (
                snapshot_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, canonical_url TEXT NOT NULL,
                content_hash TEXT NOT NULL, payload_json TEXT NOT NULL, retrieved_at TEXT NOT NULL,
                UNIQUE(source_id, canonical_url, content_hash)
            );
            CREATE TABLE IF NOT EXISTS extracted_claims (
                claim_id TEXT PRIMARY KEY, claim_hash TEXT NOT NULL UNIQUE, snapshot_id TEXT NOT NULL,
                source_id TEXT NOT NULL, subject TEXT NOT NULL, stance TEXT NOT NULL, payload_json TEXT NOT NULL,
                observed_at TEXT NOT NULL, FOREIGN KEY(snapshot_id) REFERENCES content_snapshots(snapshot_id)
            );
            CREATE TABLE IF NOT EXISTS opportunity_candidates (
                candidate_id TEXT PRIMARY KEY, candidate_hash TEXT NOT NULL UNIQUE, category TEXT NOT NULL,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS portfolio_decisions (
                decision_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE, decision TEXT NOT NULL,
                principal TEXT NOT NULL, payload_json TEXT NOT NULL, decided_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES opportunity_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS experiment_mandates (
                mandate_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, mandate_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, issued_at TEXT NOT NULL,
                FOREIGN KEY(candidate_id) REFERENCES opportunity_candidates(candidate_id)
            );
            CREATE TABLE IF NOT EXISTS scout_runs (
                run_id TEXT PRIMARY KEY, query_id TEXT NOT NULL, status TEXT NOT NULL,
                payload_json TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS source_manifests_immutable_update BEFORE UPDATE ON source_manifests BEGIN SELECT RAISE(ABORT, 'source manifests are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS source_manifests_immutable_delete BEFORE DELETE ON source_manifests BEGIN SELECT RAISE(ABORT, 'source manifests are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS snapshots_immutable_update BEFORE UPDATE ON content_snapshots BEGIN SELECT RAISE(ABORT, 'content snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS snapshots_immutable_delete BEFORE DELETE ON content_snapshots BEGIN SELECT RAISE(ABORT, 'content snapshots are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS claims_immutable_update BEFORE UPDATE ON extracted_claims BEGIN SELECT RAISE(ABORT, 'extracted claims are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS claims_immutable_delete BEFORE DELETE ON extracted_claims BEGIN SELECT RAISE(ABORT, 'extracted claims are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS candidates_immutable_update BEFORE UPDATE ON opportunity_candidates BEGIN SELECT RAISE(ABORT, 'opportunity candidates are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS candidates_immutable_delete BEFORE DELETE ON opportunity_candidates BEGIN SELECT RAISE(ABORT, 'opportunity candidates are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS decisions_immutable_update BEFORE UPDATE ON portfolio_decisions BEGIN SELECT RAISE(ABORT, 'portfolio decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS decisions_immutable_delete BEFORE DELETE ON portfolio_decisions BEGIN SELECT RAISE(ABORT, 'portfolio decisions are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mandates_immutable_update BEFORE UPDATE ON experiment_mandates BEGIN SELECT RAISE(ABORT, 'experiment mandates are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS mandates_immutable_delete BEFORE DELETE ON experiment_mandates BEGIN SELECT RAISE(ABORT, 'experiment mandates are immutable'); END;
            """)

    def add_manifest(self, item: SourceAdapterManifest, created_at: str) -> SourceAdapterManifest:
        payload = source_manifest_payload(item)
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO source_manifests VALUES (?, ?, ?, ?)", (item.adapter_id, item.manifest_hash, _dump(payload), created_at))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM source_manifests WHERE adapter_id=? OR manifest_hash=?", (item.adapter_id, item.manifest_hash)).fetchone()
                if row:
                    return source_manifest_from_payload(_load(row["payload_json"]))
                raise
        return item

    def manifests(self) -> list[SourceAdapterManifest]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM source_manifests ORDER BY adapter_id").fetchall()
        return [source_manifest_from_payload(_load(row["payload_json"])) for row in rows]

    def add_status(self, item: SourceAdapterStatus) -> SourceAdapterStatus:
        payload = {
            "source_id": item.source_id, "adapter_id": item.adapter_id, "health": item.health.value,
            "reason": item.reason, "version": item.version, "checked_at": item.checked_at,
            "latency_ms": item.latency_ms, "metadata": dict(item.metadata),
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO source_status(adapter_id, health, payload_json, checked_at) VALUES (?, ?, ?, ?)", (item.adapter_id, item.health.value, _dump(payload), item.checked_at))
        return item

    def latest_statuses(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
            SELECT payload_json FROM source_status s WHERE status_id=(SELECT MAX(status_id) FROM source_status WHERE adapter_id=s.adapter_id) ORDER BY adapter_id
            """).fetchall()
        return [_load(row["payload_json"]) for row in rows]

    def add_snapshot(self, item: ContentSnapshot) -> ContentSnapshot:
        payload = content_snapshot_payload(item)
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO content_snapshots VALUES (?, ?, ?, ?, ?, ?)", (item.snapshot_id, item.source_id, item.canonical_url, item.content_hash, _dump(payload), item.retrieved_at))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM content_snapshots WHERE source_id=? AND canonical_url=? AND content_hash=?", (item.source_id, item.canonical_url, item.content_hash)).fetchone()
                if row:
                    return content_snapshot_from_payload(_load(row["payload_json"]))
                raise
        return item

    def get_snapshot(self, snapshot_id: str) -> ContentSnapshot:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM content_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            raise OpportunityNotFound(snapshot_id)
        return content_snapshot_from_payload(_load(row["payload_json"]))

    def list_snapshots(self, limit: int = 100) -> list[ContentSnapshot]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM content_snapshots ORDER BY retrieved_at DESC LIMIT ?", (limit,)).fetchall()
        return [content_snapshot_from_payload(_load(row["payload_json"])) for row in rows]

    def add_claim(self, item: ExtractedClaim) -> ExtractedClaim:
        payload = extracted_claim_payload(item)
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO extracted_claims VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (item.claim_id, item.claim_hash, item.snapshot_id, item.source_id, item.subject, item.stance.value, _dump(payload), item.observed_at))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM extracted_claims WHERE claim_hash=?", (item.claim_hash,)).fetchone()
                if row:
                    return extracted_claim_from_payload(_load(row["payload_json"]))
                raise
        return item

    def get_claim(self, claim_id: str) -> ExtractedClaim:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM extracted_claims WHERE claim_id=?", (claim_id,)).fetchone()
        if not row:
            raise OpportunityNotFound(claim_id)
        return extracted_claim_from_payload(_load(row["payload_json"]))

    def claims(self, *, subject: str | None = None, limit: int = 500) -> list[ExtractedClaim]:
        with self._connect() as conn:
            if subject:
                rows = conn.execute("SELECT payload_json FROM extracted_claims WHERE subject=? ORDER BY observed_at DESC LIMIT ?", (subject, limit)).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM extracted_claims ORDER BY observed_at DESC LIMIT ?", (limit,)).fetchall()
        return [extracted_claim_from_payload(_load(row["payload_json"])) for row in rows]

    def add_candidate(self, item: OpportunityCandidate) -> OpportunityCandidate:
        payload = opportunity_candidate_payload(item)
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO opportunity_candidates VALUES (?, ?, ?, ?, ?, ?)", (item.candidate_id, item.candidate_hash, item.category, item.status.value, _dump(payload), item.created_at))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM opportunity_candidates WHERE candidate_hash=?", (item.candidate_hash,)).fetchone()
                if row:
                    return opportunity_candidate_from_payload(_load(row["payload_json"]))
                raise
        return item

    def get_candidate(self, candidate_id: str) -> OpportunityCandidate:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM opportunity_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            raise OpportunityNotFound(candidate_id)
        return opportunity_candidate_from_payload(_load(row["payload_json"]))

    def candidates(self, limit: int = 100) -> list[OpportunityCandidate]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM opportunity_candidates ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [opportunity_candidate_from_payload(_load(row["payload_json"])) for row in rows]

    def add_decision(self, item: PortfolioDecision) -> PortfolioDecision:
        payload = {
            "candidate_id": item.candidate_id, "decision": item.decision.value, "principal": item.principal,
            "reason": item.reason, "allocated_budget_usd": item.allocated_budget_usd, "channel": item.channel,
            "decision_id": item.decision_id, "decided_at": item.decided_at,
        }
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO portfolio_decisions VALUES (?, ?, ?, ?, ?, ?)", (item.decision_id, item.candidate_id, item.decision.value, item.principal, _dump(payload), item.decided_at))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM portfolio_decisions WHERE candidate_id=?", (item.candidate_id,)).fetchone()
                if row:
                    existing = _load(row["payload_json"])
                    if existing["decision"] != item.decision.value:
                        raise PortfolioDecisionConflict(f"candidate {item.candidate_id} already decided as {existing['decision']}")
                    return PortfolioDecision(
                        candidate_id=existing["candidate_id"], decision=PortfolioDecisionType(existing["decision"]), principal=existing["principal"],
                        reason=existing["reason"], allocated_budget_usd=float(existing["allocated_budget_usd"]), channel=existing["channel"],
                        decision_id=existing["decision_id"], decided_at=existing["decided_at"],
                    )
                raise
        return item

    def decision(self, candidate_id: str) -> PortfolioDecision | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM portfolio_decisions WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            return None
        data = _load(row["payload_json"])
        return PortfolioDecision(candidate_id=data["candidate_id"], decision=PortfolioDecisionType(data["decision"]), principal=data["principal"], reason=data["reason"], allocated_budget_usd=float(data["allocated_budget_usd"]), channel=data["channel"], decision_id=data["decision_id"], decided_at=data["decided_at"])

    def add_mandate(self, item: ExperimentMandate) -> ExperimentMandate:
        with self._connect() as conn:
            conn.execute("INSERT INTO experiment_mandates VALUES (?, ?, ?, ?, ?, ?)", (item.mandate_id, item.candidate_id, item.mandate_hash, item.status.value, _dump(experiment_mandate_payload(item)), item.issued_at))
        return item

    def mandates(self, candidate_id: str | None = None) -> list[ExperimentMandate]:
        with self._connect() as conn:
            if candidate_id:
                rows = conn.execute("SELECT payload_json FROM experiment_mandates WHERE candidate_id=? ORDER BY issued_at DESC", (candidate_id,)).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM experiment_mandates ORDER BY issued_at DESC").fetchall()
        return [experiment_mandate_from_payload(_load(row["payload_json"])) for row in rows]

    def add_run(self, item: ScoutRunReceipt) -> ScoutRunReceipt:
        payload = {
            "query_id": item.query_id, "status": item.status, "source_ids": list(item.source_ids),
            "snapshot_ids": list(item.snapshot_ids), "claim_ids": list(item.claim_ids), "candidate_ids": list(item.candidate_ids),
            "bytes_consumed": item.bytes_consumed, "duration_seconds": item.duration_seconds, "blockers": list(item.blockers),
            "metadata": dict(item.metadata), "run_id": item.run_id, "started_at": item.started_at, "completed_at": item.completed_at,
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO scout_runs VALUES (?, ?, ?, ?, ?, ?)", (item.run_id, item.query_id, item.status, _dump(payload), item.started_at, item.completed_at))
        return item

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM scout_runs ORDER BY completed_at DESC LIMIT ?", (limit,)).fetchall()
        return [_load(row["payload_json"]) for row in rows]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = {}
            for table in ("source_manifests", "content_snapshots", "extracted_claims", "opportunity_candidates", "portfolio_decisions", "experiment_mandates", "scout_runs"):
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return {"store_id": self.store_id, "path": str(self.path), **counts}
