from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import write_json
from aether.utils.time import utc_now

INGESTION_DIRS = [
    "ingestion/inbox",
    "ingestion/processed",
    "ingestion/rejected",
    "runtime_state/ingestion",
    "runtime_state/ingestion/archive",
    "runtime_state/ingestion/jobs",
    "runtime_state/ingestion/indexes",
    "runtime_state/reports",
]


def ensure_ingestion_workspace(root: Path) -> dict[str, Any]:
    created = []
    for rel in INGESTION_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(path.relative_to(root).as_posix())

    readme = root / "ingestion" / "inbox" / "README.md"
    if not readme.exists():
        readme.write_text(
            "# SNIPER Ingestion Inbox\n\n"
            "Drop `.txt`, `.md`, `.markdown`, `.json`, `.csv`, `.html`, or `.htm` files here, then run:\n\n"
            "`PYTHONPATH=src python -m aether.cli ingestion-process-inbox .`\n",
            encoding="utf-8",
        )

    report = {"ok": True, "timestamp": utc_now(), "created_or_confirmed": created}
    write_json(root / "runtime_state" / "reports" / "ingestion_workspace_init.json", report)
    return report


def manifest_path(root: Path) -> Path:
    return root / "runtime_state" / "ingestion" / "manifest.jsonl"


def archive_dir(root: Path) -> Path:
    return root / "runtime_state" / "ingestion" / "archive"


def inbox_dir(root: Path) -> Path:
    return root / "ingestion" / "inbox"


def processed_dir(root: Path) -> Path:
    return root / "ingestion" / "processed"


def rejected_dir(root: Path) -> Path:
    return root / "ingestion" / "rejected"
