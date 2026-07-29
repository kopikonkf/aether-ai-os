from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aether.utils.ids import new_id
from aether.utils.jsonio import append_jsonl, read_jsonl
from aether.utils.time import utc_now


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_entry(entry_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(entry_without_hash).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str
    evidence_links: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    ledger_id: str = field(default_factory=lambda: new_id("led"))
    timestamp: str = field(default_factory=utc_now)
    correlation_id: str | None = None
    previous_hash: str | None = None
    hash: str | None = None

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "summary": self.summary,
            "evidence_links": self.evidence_links,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "previous_hash": self.previous_hash,
        }

    def signed_dict(self) -> dict[str, Any]:
        data = self.unsigned_dict()
        data["hash"] = self.hash or _hash_entry(data)
        return data


class AppendOnlyLedger:
    """Append-only JSONL ledger with chained SHA-256 hashes."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def entries(self) -> list[dict[str, Any]]:
        return read_jsonl(self.path)

    def last_hash(self) -> str | None:
        rows = self.entries()
        if not rows:
            return None
        return rows[-1].get("hash")

    def append(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        summary: str,
        evidence_links: list[str] | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        entry = LedgerEntry(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            evidence_links=evidence_links or [],
            payload=payload or {},
            correlation_id=correlation_id,
            previous_hash=self.last_hash(),
        )
        signed = entry.signed_dict()
        append_jsonl(self.path, signed)
        return signed

    def verify(self) -> dict[str, Any]:
        rows = self.entries()
        errors: list[str] = []
        previous_hash = None
        for idx, row in enumerate(rows):
            actual_hash = row.get("hash")
            if row.get("previous_hash") != previous_hash:
                errors.append(f"row {idx}: previous_hash mismatch")
            unsigned = dict(row)
            unsigned.pop("hash", None)
            expected_hash = _hash_entry(unsigned)
            if actual_hash != expected_hash:
                errors.append(f"row {idx}: hash mismatch")
            previous_hash = actual_hash
        return {
            "ok": not errors,
            "entry_count": len(rows),
            "last_hash": previous_hash,
            "errors": errors,
        }
