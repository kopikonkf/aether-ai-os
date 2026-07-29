"""Rebuildable local lexical retrieval provider.

This provider is intentionally simple and dependency-free. It proves the
MemoryProvider contract without making the retrieval index authoritative.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Sequence

from aether.contracts.memory import MemoryRecord
from .canonical import SQLiteCanonicalMemoryStore

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return [item.casefold() for item in _TOKEN.findall(text) if len(item) > 1]


class SQLiteLexicalMemoryProvider:
    provider_id = "aether.memory.retrieval.sqlite-lexical"

    def __init__(self, path: Path, canonical: SQLiteCanonicalMemoryStore) -> None:
        self.path = path
        self.canonical = canonical
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS indexed_records (
                    record_id TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_terms (
                    term TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    frequency INTEGER NOT NULL,
                    PRIMARY KEY(term, record_id),
                    FOREIGN KEY(record_id) REFERENCES indexed_records(record_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_terms_term ON memory_terms(term);
                """
            )

    async def store(self, record: MemoryRecord) -> None:
        if not record.record_id:
            raise ValueError("record must be canonicalized before indexing")
        tokens = _tokens(record.content)
        counts = Counter(tokens)
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO indexed_records(record_id, namespace, content, token_count) VALUES (?, ?, ?, ?)",
                    (record.record_id, record.namespace, record.content, len(tokens)),
                )
                conn.execute("DELETE FROM memory_terms WHERE record_id = ?", (record.record_id,))
                conn.executemany(
                    "INSERT INTO memory_terms(term, record_id, frequency) VALUES (?, ?, ?)",
                    [(term, record.record_id, frequency) for term, frequency in counts.items()],
                )

    async def recall(self, key: str, namespace: str = "default") -> MemoryRecord | None:
        return await self.canonical.by_key(key, namespace)

    async def search(self, query: str, namespace: str = "default", limit: int = 10) -> Sequence[MemoryRecord]:
        ranked = await self.search_scored(query, namespaces=(namespace,), limit=limit)
        return tuple(record for record, _score, _reasons in ranked)

    async def search_scored(
        self,
        query: str,
        *,
        namespaces: tuple[str, ...] = (),
        limit: int = 10,
    ) -> tuple[tuple[MemoryRecord, float, tuple[str, ...]], ...]:
        terms = tuple(dict.fromkeys(_tokens(query)))
        if not terms or limit < 1:
            return ()
        placeholders = ",".join("?" for _ in terms)
        clauses = [f"t.term IN ({placeholders})"]
        params: list[object] = list(terms)
        if namespaces:
            clauses.append("r.namespace IN (%s)" % ",".join("?" for _ in namespaces))
            params.extend(namespaces)
        sql = f"""
            SELECT r.record_id, r.token_count, t.term, t.frequency
            FROM memory_terms t
            JOIN indexed_records r ON r.record_id = t.record_id
            WHERE {' AND '.join(clauses)}
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        grouped: dict[str, dict[str, object]] = {}
        for row in rows:
            item = grouped.setdefault(row["record_id"], {"matched": set(), "frequency": 0, "length": row["token_count"]})
            item["matched"].add(row["term"])
            item["frequency"] = int(item["frequency"]) + int(row["frequency"])
        scored: list[tuple[str, float, tuple[str, ...]]] = []
        for record_id, item in grouped.items():
            matched = item["matched"]
            coverage = len(matched) / len(terms)
            density = min(1.0, int(item["frequency"]) / max(1.0, math.sqrt(int(item["length"]) or 1)))
            score = round(0.8 * coverage + 0.2 * density, 6)
            scored.append((record_id, score, tuple(sorted(matched))))
        scored.sort(key=lambda item: (-item[1], item[0]))
        result = []
        for record_id, score, reasons in scored[:limit]:
            record = await self.canonical.get(record_id)
            if record is not None:
                result.append((record, score, reasons))
        return tuple(result)

    async def rebuild(self) -> int:
        records = await self.canonical.list()
        async with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM memory_terms")
                conn.execute("DELETE FROM indexed_records")
        for record in records:
            await self.store(record)
        return len(records)

    async def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM indexed_records").fetchone()
        return int(row["n"])
