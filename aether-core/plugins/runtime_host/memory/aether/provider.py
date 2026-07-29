"""Aether-backed runtime memory bridge.

Operational turns are canonical episodes. They are never promoted directly to
beliefs; belief formation remains governed by Aether's knowledge lifecycle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from aether.contracts import MemoryKind, MemoryProvenance, MemoryRecord
from aether.memory import SQLiteCanonicalMemoryStore
from aether.paths import get_aether_home
from aether.utils.ids import new_id
from aether.utils.time import utc_now


class AetherMemoryCore:
    def __init__(self, client, canonical_path: Path | None = None):
        self.client = client
        self.store = SQLiteCanonicalMemoryStore(
            canonical_path or (get_aether_home() / "memory" / "canonical-episodes.sqlite3")
        )

    def prefetch(self, query: str) -> str:
        if not self.client.is_alive():
            return ""
        try:
            me = self.client.who_am_i()
            return f"Mind stage={me.stage}; self={me.narrative[:200]}"
        except Exception:
            return ""

    def write_operational(self, content: str, *, session_id: str = "") -> Dict[str, Any]:
        record = self.store.append_sync(MemoryRecord(
            key=new_id("runtime-turn"),
            value={"content": content},
            namespace="episodes",
            kind=MemoryKind.EPISODE,
            content=content,
            metadata={"session_id": session_id, "bridge": "runtime_host"},
            provenance=MemoryProvenance(
                source="runtime-host-memory-bridge",
                observed_at=utc_now(),
                session_id=session_id or None,
            ),
        ))
        return {"ok": True, "record_id": record.record_id, "content_hash": record.content_hash}
