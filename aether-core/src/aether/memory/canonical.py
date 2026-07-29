"""Aether-owned canonical episodic store.

The canonical store is authoritative for episodes. Retrieval providers and
Obsidian are rebuildable projections and may be deleted without data loss.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable

from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.utils.time import utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _content_for(record: MemoryRecord) -> str:
    if record.content.strip():
        return record.content.strip()
    if isinstance(record.value, str):
        return record.value.strip()
    return _json(record.value)


def _canonical_hash(record: MemoryRecord, content: str) -> str:
    payload = {
        "key": record.key,
        "namespace": record.namespace,
        "kind": record.kind.value,
        "content": content,
        "provenance": asdict(record.provenance) if record.provenance else None,
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class SQLiteCanonicalMemoryStore:
    """Append-only canonical records with deterministic integrity metadata."""

    provider_id = "aether.memory.canonical.sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
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
                CREATE TABLE IF NOT EXISTS memory_records (
                    record_id TEXT PRIMARY KEY,
                    record_key TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    provenance_json TEXT,
                    created_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_namespace_created
                    ON memory_records(namespace, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memory_kind_created
                    ON memory_records(kind, created_at DESC);

                CREATE TRIGGER IF NOT EXISTS memory_records_no_update
                BEFORE UPDATE ON memory_records
                BEGIN
                    SELECT RAISE(ABORT, 'canonical memory is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS memory_records_no_delete
                BEFORE DELETE ON memory_records
                BEGIN
                    SELECT RAISE(ABORT, 'canonical memory is append-only');
                END;
                """
            )

    async def append(self, record: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            return self.append_sync(record)

    def append_sync(self, record: MemoryRecord) -> MemoryRecord:
        """Synchronous bridge for host runtimes that do not expose an async hook."""
        content = _content_for(record)
        created_at = record.created_at or utc_now()
        content_hash = record.content_hash or _canonical_hash(record, content)
        record_id = record.record_id or f"mem.{content_hash[:24]}"
        normalized = replace(
            record,
            record_id=record_id,
            content=content,
            created_at=created_at,
            content_hash=content_hash,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO memory_records (
                    record_id, record_key, namespace, kind, value_json, content,
                    metadata_json, provenance_json, created_at, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized.record_id,
                    normalized.key,
                    normalized.namespace,
                    normalized.kind.value,
                    _json(normalized.value),
                    normalized.content,
                    _json(dict(normalized.metadata)),
                    _json(asdict(normalized.provenance)) if normalized.provenance else None,
                    normalized.created_at,
                    normalized.content_hash,
                ),
            )
            row = conn.execute(
                "SELECT * FROM memory_records WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        if row is None:
            raise RuntimeError("canonical memory append failed")
        return self._row_to_record(row)

    async def get(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    async def by_key(self, key: str, namespace: str = "default") -> MemoryRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM memory_records
                   WHERE record_key = ? AND namespace = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (key, namespace),
            ).fetchone()
        return self._row_to_record(row) if row else None

    async def list(
        self,
        *,
        namespaces: Iterable[str] | None = None,
        kinds: Iterable[MemoryKind] | None = None,
        limit: int | None = None,
    ) -> tuple[MemoryRecord, ...]:
        clauses: list[str] = []
        params: list[Any] = []
        namespaces = tuple(namespaces or ())
        kinds = tuple(kinds or ())
        if namespaces:
            clauses.append("namespace IN (%s)" % ",".join("?" for _ in namespaces))
            params.extend(namespaces)
        if kinds:
            clauses.append("kind IN (%s)" % ",".join("?" for _ in kinds))
            params.extend(item.value for item in kinds)
        sql = "SELECT * FROM memory_records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    async def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM memory_records").fetchone()
        return int(row["n"])

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        provenance = None
        if row["provenance_json"]:
            data = json.loads(row["provenance_json"])
            provenance = MemoryProvenance(
                source=data["source"],
                observed_at=data["observed_at"],
                session_id=data.get("session_id"),
                correlation_id=data.get("correlation_id"),
                event_ids=tuple(data.get("event_ids") or ()),
                evidence_links=tuple(data.get("evidence_links") or ()),
            )
        return MemoryRecord(
            key=row["record_key"],
            value=json.loads(row["value_json"]),
            namespace=row["namespace"],
            metadata=json.loads(row["metadata_json"]),
            record_id=row["record_id"],
            kind=MemoryKind(row["kind"]),
            content=row["content"],
            provenance=provenance,
            created_at=row["created_at"],
            content_hash=row["content_hash"],
        )
