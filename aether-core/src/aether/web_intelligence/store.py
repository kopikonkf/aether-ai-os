"""Append-only SQLite ledger for live source configuration, conformance, freshness, and discovery."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from aether.contracts.web_intelligence import (
    EvidenceFreshnessRecord, FreshnessState, LiveSourceConfiguration,
    SourceConformanceReceipt, SourceConformanceState, SourceDiscoveryCandidate,
    SourceDiscoveryState, WebIntelligenceNotFound, freshness_record_payload,
    live_source_configuration_from_payload, live_source_configuration_payload,
    source_conformance_receipt_from_payload, source_conformance_receipt_payload,
    source_discovery_candidate_payload,
)


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: str) -> Any:
    return json.loads(value)


class SQLiteWebIntelligenceStore:
    store_id = "web-intelligence.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS live_source_configurations(
                config_id TEXT PRIMARY KEY, adapter_id TEXT NOT NULL, configuration_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL, configured_at TEXT NOT NULL,
                UNIQUE(adapter_id, configuration_hash)
            );
            CREATE TABLE IF NOT EXISTS source_conformance_receipts(
                receipt_id TEXT PRIMARY KEY, adapter_id TEXT NOT NULL, receipt_hash TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL, payload_json TEXT NOT NULL, issued_at TEXT NOT NULL, expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_freshness_records(
                record_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, state TEXT NOT NULL,
                payload_json TEXT NOT NULL, evaluated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_discovery_candidates(
                candidate_id TEXT PRIMARY KEY, candidate_hash TEXT NOT NULL UNIQUE, domain TEXT NOT NULL,
                state TEXT NOT NULL, payload_json TEXT NOT NULL, proposed_at TEXT NOT NULL
            );
            """)
            for table in (
                "live_source_configurations", "source_conformance_receipts",
                "evidence_freshness_records", "source_discovery_candidates",
            ):
                conn.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable append-only ledger'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable append-only ledger'); END;
                """)

    def add_configuration(self, item: LiveSourceConfiguration) -> LiveSourceConfiguration:
        payload = live_source_configuration_payload(item)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO live_source_configurations VALUES (?, ?, ?, ?, ?)",
                    (item.config_id, item.adapter_id, item.configuration_hash, _dump(payload), item.configured_at),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT payload_json FROM live_source_configurations WHERE adapter_id=? AND configuration_hash=?",
                    (item.adapter_id, item.configuration_hash),
                ).fetchone()
                if row:
                    return live_source_configuration_from_payload(_load(row["payload_json"]))
                raise
        return item

    def latest_configuration(self, adapter_id: str) -> LiveSourceConfiguration | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM live_source_configurations WHERE adapter_id=? ORDER BY configured_at DESC, rowid DESC LIMIT 1",
                (adapter_id,),
            ).fetchone()
        return live_source_configuration_from_payload(_load(row["payload_json"])) if row else None

    def configurations(self) -> list[LiveSourceConfiguration]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT payload_json FROM live_source_configurations c
                WHERE rowid=(SELECT MAX(rowid) FROM live_source_configurations WHERE adapter_id=c.adapter_id)
                ORDER BY adapter_id
            """).fetchall()
        return [live_source_configuration_from_payload(_load(row["payload_json"])) for row in rows]

    def add_conformance(self, item: SourceConformanceReceipt) -> SourceConformanceReceipt:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO source_conformance_receipts VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item.receipt_id, item.adapter_id, item.receipt_hash, item.state.value,
                     _dump(source_conformance_receipt_payload(item)), item.issued_at, item.expires_at),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT payload_json FROM source_conformance_receipts WHERE receipt_hash=?",
                    (item.receipt_hash,),
                ).fetchone()
                if row:
                    return source_conformance_receipt_from_payload(_load(row["payload_json"]))
                raise
        return item

    def latest_conformance(self, adapter_id: str) -> SourceConformanceReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM source_conformance_receipts WHERE adapter_id=? ORDER BY issued_at DESC, rowid DESC LIMIT 1",
                (adapter_id,),
            ).fetchone()
        return source_conformance_receipt_from_payload(_load(row["payload_json"])) if row else None

    def add_freshness(self, item: EvidenceFreshnessRecord) -> EvidenceFreshnessRecord:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evidence_freshness_records VALUES (?, ?, ?, ?, ?)",
                (item.record_id, item.snapshot_id, item.state.value, _dump(freshness_record_payload(item)), item.evaluated_at),
            )
        return item

    def latest_freshness(self, snapshot_id: str) -> EvidenceFreshnessRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM evidence_freshness_records WHERE snapshot_id=? ORDER BY evaluated_at DESC, rowid DESC LIMIT 1",
                (snapshot_id,),
            ).fetchone()
        if not row:
            return None
        data = _load(row["payload_json"])
        return EvidenceFreshnessRecord(
            snapshot_id=data["snapshot_id"], source_id=data["source_id"], canonical_url=data["canonical_url"],
            retrieved_at=data["retrieved_at"], evaluated_at=data["evaluated_at"], age_seconds=int(data["age_seconds"]),
            state=FreshnessState(data["state"]), refresh_required=bool(data["refresh_required"]),
            content_hash=data["content_hash"], metadata=dict(data.get("metadata", {})), record_id=data["record_id"],
        )

    def freshness_records(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM evidence_freshness_records ORDER BY evaluated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_load(row["payload_json"]) for row in rows]

    def add_discovery(self, item: SourceDiscoveryCandidate) -> SourceDiscoveryCandidate:
        payload = source_discovery_candidate_payload(item)
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO source_discovery_candidates VALUES (?, ?, ?, ?, ?, ?)",
                    (item.candidate_id, item.candidate_hash, item.canonical_domain, item.state.value,
                     _dump(payload), item.proposed_at),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT payload_json FROM source_discovery_candidates WHERE candidate_hash=?",
                    (item.candidate_hash,),
                ).fetchone()
                if row:
                    return self._discovery_from_data(_load(row["payload_json"]))
                raise
        return item

    @staticmethod
    def _discovery_from_data(data: dict[str, Any]) -> SourceDiscoveryCandidate:
        return SourceDiscoveryCandidate(
            discovered_url=data["discovered_url"], canonical_domain=data["canonical_domain"],
            discovered_from_snapshot_ids=tuple(data.get("discovered_from_snapshot_ids", ())),
            capabilities=tuple(data.get("capabilities", ())), reason=data["reason"],
            confidence=float(data["confidence"]), risk=data["risk"], state=SourceDiscoveryState(data["state"]),
            metadata=dict(data.get("metadata", {})), candidate_id=data["candidate_id"],
            proposed_at=data.get("proposed_at", ""), decided_by=data.get("decided_by"),
            decided_at=data.get("decided_at"), decision_reason=data.get("decision_reason"),
            candidate_hash=data.get("candidate_hash", ""),
        )

    def get_discovery(self, candidate_id: str) -> SourceDiscoveryCandidate:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM source_discovery_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            raise WebIntelligenceNotFound(candidate_id)
        return self._discovery_from_data(_load(row["payload_json"]))

    def discoveries(self, limit: int = 200) -> list[SourceDiscoveryCandidate]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM source_discovery_candidates ORDER BY proposed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._discovery_from_data(_load(row["payload_json"])) for row in rows]

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
                "live_source_configurations", "source_conformance_receipts",
                "evidence_freshness_records", "source_discovery_candidates",
            )}
        return {"store_id": self.store_id, "path": str(self.path), **counts}
