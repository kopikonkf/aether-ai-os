"""NorthStar-aware Goal Engine."""

from .workspace import ensure_goal_workspace
from .engine import (
    create_goal,
    list_goals,
    add_key_result,
    update_key_result_progress,
    score_goal,
    prioritize_goals,
    change_goal_status,
)
from .indexer import build_goal_index, goal_status, validate_goal_workspace

__all__ = [
    "ensure_goal_workspace",
    "create_goal",
    "list_goals",
    "add_key_result",
    "update_key_result_progress",
    "score_goal",
    "prioritize_goals",
    "change_goal_status",
    "build_goal_index",
    "goal_status",
    "validate_goal_workspace",
]
