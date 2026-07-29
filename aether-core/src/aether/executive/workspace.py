from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import write_json
from aether.utils.time import utc_now

EXECUTIVE_DIRS = [
    'runtime_state/executive',
    'runtime_state/executive/indexes',
    'runtime_state/reports',
    'obsidian/vault/09_Decisions',
    'obsidian/vault/10_Reports',
    'obsidian/vault/00_System/indexes',
]


def ensure_executive_workspace(root: Path) -> dict[str, Any]:
    created = []
    for rel in EXECUTIVE_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(path.relative_to(root).as_posix())
    report = {
        'ok': True,
        'timestamp': utc_now(),
        'created_or_confirmed': created,
        'workspace': (root / 'runtime_state' / 'executive').relative_to(root).as_posix(),
    }
    write_json(root / 'runtime_state' / 'reports' / 'executive_workspace_init.json', report)
    return report


def decisions_path(root: Path) -> Path:
    return root / 'runtime_state' / 'executive' / 'decisions.jsonl'


def runs_path(root: Path) -> Path:
    return root / 'runtime_state' / 'executive' / 'runs.jsonl'


def heartbeats_path(root: Path) -> Path:
    return root / 'runtime_state' / 'executive' / 'heartbeats.jsonl'


def executive_index_path(root: Path) -> Path:
    return root / 'runtime_state' / 'executive' / 'index.json'
