"""Daily spend gate for Baby stage economic loop."""
from __future__ import annotations


class BudgetGate:
    def __init__(self, daily_cap_usd: float = 10.0, spent_today: float = 0.0):
        self.daily_cap_usd = daily_cap_usd
        self.spent_today = spent_today

    def allow(self, amount_usd: float) -> bool:
        if amount_usd < 0:
            return False
        return (self.spent_today + amount_usd) <= self.daily_cap_usd

    def record(self, amount_usd: float) -> None:
        self.spent_today += amount_usd
