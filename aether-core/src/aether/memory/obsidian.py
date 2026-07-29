"""Human-readable Obsidian projection for curated memory artifacts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Sequence

from aether.contracts.memory import MemoryRecord
from aether.utils.time import utc_now


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip()).strip("-").lower()
    return value or "memory"


def _yaml_escape(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


class ObsidianMemoryProjector:
    projector_id = "aether.memory.obsidian-projection"

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self.target = self.vault_root / "04_Digests" / "Aether Memory"
        self.target.mkdir(parents=True, exist_ok=True)
        system = self.vault_root / "00_System"
        system.mkdir(parents=True, exist_ok=True)
        index = system / "Aether_Memory_Index.md"
        if not index.exists():
            index.write_text(
                "# Aether Memory Index\n\n"
                "This vault is a human-readable projection. Canonical authority remains in Aether's episodic store.\n",
                encoding="utf-8",
            )

    async def project_session(self, session_id: str, records: Sequence[MemoryRecord], *, title: str | None = None) -> Path:
        title = title or f"Session {session_id}"
        path = self.target / f"{_slug(session_id)}.md"
        lines = [
            "---",
            f"title: {_yaml_escape(title)}",
            "type: session_digest",
            f"session_id: {_yaml_escape(session_id)}",
            f"projected_at: {_yaml_escape(utc_now())}",
            "authority: projection_only",
            "---",
            "",
            f"# {title}",
            "",
            "> This note is rebuildable. Canonical memory remains in Aether.",
            "",
        ]
        for record in sorted(records, key=lambda item: item.created_at or ""):
            source = record.provenance.source if record.provenance else "unknown"
            lines.extend([
                f"## {record.kind.value.title()} — {record.created_at or 'unknown time'}",
                "",
                record.content,
                "",
                f"- Record: `{record.record_id}`",
                f"- Source: `{source}`",
                f"- Content hash: `{record.content_hash}`",
                "",
            ])
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return path
