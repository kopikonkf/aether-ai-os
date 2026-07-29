from aether.adapters.budget import BudgetGate


def test_allows_under_cap():
    g = BudgetGate(daily_cap_usd=10.0, spent_today=3.0)
    assert g.allow(5.0) is True


def test_blocks_over_cap():
    g = BudgetGate(daily_cap_usd=10.0, spent_today=8.0)
    assert g.allow(5.0) is False
