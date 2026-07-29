from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.utils.jsonio import read_json, write_json
from aether.utils.time import utc_now

GOAL_DIRS = [
    "runtime_state/goals",
    "runtime_state/goals/indexes",
    "runtime_state/reports",
    "obsidian/vault/01_Objectives",
    "obsidian/vault/00_System/indexes",
]


def ensure_goal_workspace(root: Path) -> dict[str, Any]:
    created = []
    for rel in GOAL_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True)
        created.append(path.relative_to(root).as_posix())
    registry = goals_path(root)
    if not registry.exists():
        write_json(registry, [])
    report = {"ok": True, "timestamp": utc_now(), "created_or_confirmed": created, "registry": registry.relative_to(root).as_posix()}
    write_json(root / "runtime_state" / "reports" / "goal_workspace_init.json", report)
    return report


def goals_path(root: Path) -> Path:
    return root / "runtime_state" / "goals" / "goals.json"


def goal_events_path(root: Path) -> Path:
    return root / "runtime_state" / "goals" / "goal_events.jsonl"


def goal_index_path(root: Path) -> Path:
    return root / "runtime_state" / "goals" / "index.json"


def read_goals(root: Path) -> list[dict[str, Any]]:
    ensure_goal_workspace(root)
    data = read_json(goals_path(root), default=[])
    return data if isinstance(data, list) else []


def write_goals(root: Path, goals: list[dict[str, Any]]) -> None:
    ensure_goal_workspace(root)
    write_json(goals_path(root), goals)
