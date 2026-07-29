from __future__ import annotations

from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from aether.obsidian.notes import write_note


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def create_daily_log(root: Path, activity: str, reflection: str = "", next_action: str = "") -> dict[str, Any]:
    date = today_utc()
    title = f"Daily Cognitive Log {date}"
    body = f"""# Daily Cognitive Log - {date}

## Activity
{activity}

## Reflection
{reflection or 'No reflection recorded yet.'}

## Knowledge Changes
- None recorded yet.

## Blockers
- None recorded yet.

## Next Action
{next_action or 'Continue highest-value NorthStar-aligned work.'}
"""
    return write_note(root, "diary", title, body, metadata={"date": date}, folder="08_Reflections/Daily", overwrite=True)
