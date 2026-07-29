from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import write_json
from aether.utils.time import utc_now

KNOWLEDGE_DIRS = [
    "runtime_state/knowledge",
    "runtime_state/knowledge/indexes",
    "runtime_state/knowledge/reviews",
    "runtime_state/knowledge/evidence",
    "runtime_state/reports",
    "obsidian/vault/05_Knowledge",
    "obsidian/vault/06_Beliefs",
    "obsidian/vault/00_System/indexes",
]


def ensure_knowledge_workspace(root: Path) -> dict[str, Any]:
    created = []
    for rel in KNOWLEDGE_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(path.relative_to(root).as_posix())
    readme = root / "runtime_state" / "knowledge" / "README.md"
    if not readme.exists():
        readme.write_text(
            "# Aether Knowledge Lifecycle\n\n"
            "This directory stores lifecycle claims, review decisions, evidence links, promotions, and indexes.\n",
            encoding="utf-8",
        )
    report = {"ok": True, "timestamp": utc_now(), "created_or_confirmed": created}
    write_json(root / "runtime_state" / "reports" / "knowledge_workspace_init.json", report)
    return report


def registry_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "claim_registry.json"


def lifecycle_events_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "lifecycle_events.jsonl"


def review_decisions_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "review_decisions.jsonl"


def evidence_links_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "evidence_links.jsonl"


def promotions_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "promotions.jsonl"


def knowledge_index_path(root: Path) -> Path:
    return root / "runtime_state" / "knowledge" / "index.json"
