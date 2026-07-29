from __future__ import annotations

from pathlib import Path
from typing import Any

from aether.goal.engine import prioritize_goals, score_goal
from aether.goal.workspace import ensure_goal_workspace, goal_index_path, read_goals
from aether.utils.jsonio import read_jsonl, write_json
from aether.obsidian import build_vault_index
from aether.utils.time import utc_now


def build_goal_index(root: Path, write: bool = True) -> dict[str, Any]:
    ensure_goal_workspace(root)
    goals = read_goals(root)
    by_status: dict[str, int] = {}
    by_horizon: dict[str, int] = {}
    scored = []
    for goal in goals:
        by_status[goal.get("status", "unknown")] = by_status.get(goal.get("status", "unknown"), 0) + 1
        by_horizon[goal.get("horizon", "unknown")] = by_horizon.get(goal.get("horizon", "unknown"), 0) + 1
        scored.append(score_goal(goal))
    ranked = prioritize_goals(root, write=write)["ranked_goals"] if goals else []
    events = read_jsonl(root / "runtime_state" / "goals" / "goal_events.jsonl")
    index = {
        "generated_at": utc_now(),
        "goal_count": len(goals),
        "active_goal_count": by_status.get("active", 0),
        "completed_goal_count": by_status.get("completed", 0),
        "goals_by_status": by_status,
        "goals_by_horizon": by_horizon,
        "event_count": len(events),
        "ranked_goals": ranked,
        "goals": goals,
        "scores": scored,
    }
    if write:
        write_json(goal_index_path(root), index)
        write_json(root / "runtime_state" / "goals" / "indexes" / "goals.json", goals)
        write_json(root / "runtime_state" / "goals" / "indexes" / "scores.json", scored)
        target = root / "obsidian" / "vault" / "00_System" / "indexes" / "Goal_Index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_index_md(index), encoding="utf-8")
        write_json(root / "runtime_state" / "reports" / "goal_index_latest.json", index)
        build_vault_index(root, write=True)
    return index


def _index_md(index: dict[str, Any]) -> str:
    lines = [
        "# Goal Index",
        "",
        f"Generated: {index['generated_at']}",
        f"Goals: {index['goal_count']}",
        f"Active: {index['active_goal_count']}",
        f"Completed: {index['completed_goal_count']}",
        "",
        "## Goals by Status",
    ]
    for status, count in sorted(index["goals_by_status"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Ranked Goals"])
    for item in index.get("ranked_goals", [])[:25]:
        lines.append(f"- {item['score']:.2f} — {item['title']} (`{item['goal_id']}`) — {item['verdict']}")
    return "\n".join(lines) + "\n"


def goal_status(root: Path) -> dict[str, Any]:
    ensure_goal_workspace(root)
    index = build_goal_index(root, write=True)
    return {
        "ok": True,
        "goal_count": index["goal_count"],
        "active_goal_count": index["active_goal_count"],
        "completed_goal_count": index["completed_goal_count"],
        "event_count": index["event_count"],
        "index_exists": goal_index_path(root).exists(),
        "top_goal": index["ranked_goals"][0] if index.get("ranked_goals") else None,
    }


def validate_goal_workspace(root: Path) -> dict[str, Any]:
    status = goal_status(root)
    errors = []
    required = [
        root / "runtime_state" / "goals",
        root / "runtime_state" / "goals" / "goals.json",
        root / "runtime_state" / "goals" / "index.json",
        root / "obsidian" / "vault" / "01_Objectives",
        root / "obsidian" / "vault" / "00_System" / "indexes",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"missing: {path.relative_to(root).as_posix()}")
    status["errors"] = errors
    status["ok"] = not errors
    return status
