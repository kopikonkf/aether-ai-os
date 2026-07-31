"""Persistent budget gate for Aether body actions."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class BudgetSnapshot:
    date: str
    daily_cap_usd: float
    spent_today_usd: float

    @property
    def remaining_usd(self) -> float:
        return max(self.daily_cap_usd - self.spent_today_usd, 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "daily_cap_usd": self.daily_cap_usd,
            "spent_today_usd": self.spent_today_usd,
            "remaining_usd": self.remaining_usd,
        }


class PersistentBudgetGate:
    """Budget gate backed by a JSON file under AETHER_HOME."""

    def __init__(self, path: Path | str, daily_cap_usd: float = 10.0):
        self.path = Path(path)
        self.daily_cap_usd = float(daily_cap_usd)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> BudgetSnapshot:
        today = _today_utc()
        if not self.path.exists():
            return BudgetSnapshot(today, self.daily_cap_usd, 0.0)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return BudgetSnapshot(today, self.daily_cap_usd, 0.0)
        if raw.get("date") != today:
            return BudgetSnapshot(today, self.daily_cap_usd, 0.0)
        return BudgetSnapshot(
            date=today,
            daily_cap_usd=float(raw.get("daily_cap_usd", self.daily_cap_usd)),
            spent_today_usd=float(raw.get("spent_today_usd", 0.0)),
        )

    def allow(self, amount_usd: float) -> bool:
        amount = float(amount_usd)
        if amount < 0:
            return False
        snap = self.snapshot()
        return (snap.spent_today_usd + amount) <= snap.daily_cap_usd

    def record(self, amount_usd: float) -> BudgetSnapshot:
        amount = float(amount_usd)
        if amount < 0:
            raise ValueError("amount_usd must be non-negative")
        snap = self.snapshot()
        updated = BudgetSnapshot(
            date=snap.date,
            daily_cap_usd=snap.daily_cap_usd,
            spent_today_usd=snap.spent_today_usd + amount,
        )
        self.path.write_text(json.dumps(updated.to_dict(), sort_keys=True) + "\n", encoding="utf-8")
        return updated

