from __future__ import annotations

import sqlite3
from pathlib import Path

from aether.resilience import ProviderErrorSignal
from aether.resilience.runtime import (
    ProviderProfile,
    ProviderRuntimeStateStore,
    ResilientProviderRouter,
)


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        self.now += 1
        return self.now


def profile(provider_id, priority, daily=10):
    return ProviderProfile(
        provider_id=provider_id,
        priority=priority,
        capabilities=frozenset({"voice.tts", "cognition.reason"}),
        daily_limit=daily,
        concurrency_limit=1,
        failure_threshold=1,
        cooldown_seconds=60,
        data_policy_tags=frozenset({"cloud"}),
    )


def test_state_persists_budget_across_store_reopen(tmp_path: Path):
    path = tmp_path / "runtime" / "provider-resilience.sqlite3"
    google = profile("google", 1)
    store = ProviderRuntimeStateStore(path)
    with store.reservation(google, now=100):
        assert store.candidate(google, now=100).concurrency_available == 0

    reopened = ProviderRuntimeStateStore(path)
    candidate = reopened.candidate(google, now=101)
    assert candidate.daily_budget_remaining == 9
    assert candidate.concurrency_available == 1


def test_router_persists_failure_and_falls_back(tmp_path: Path):
    store = ProviderRuntimeStateStore(tmp_path / "provider-resilience.sqlite3")
    clock = Clock()
    router = ResilientProviderRouter(
        [profile("google", 1), profile("openai", 2)], store, clock=clock
    )
    calls = []

    class Exhausted(RuntimeError):
        status_code = 429
        error_code = "insufficient_quota"

    def operation(provider_id):
        calls.append(provider_id)
        if provider_id == "google":
            raise Exhausted("quota exhausted")
        return "spoken"

    result = router.invoke(
        capability="voice.tts",
        allowed_data_policy_tags={"cloud"},
        operation=operation,
        error_signal=lambda error: ProviderErrorSignal(
            status_code=getattr(error, "status_code", None),
            error_code=getattr(error, "error_code", ""),
            message=str(error),
        ),
    )

    assert result == "spoken"
    assert calls == ["google", "openai"]
    assert store.candidate(profile("google", 1), now=clock()).circuit_state.value == "open"
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT COUNT(*) FROM provider_runtime_receipts").fetchone()[0] == 2


def test_day_rollover_resets_consumed_budget(tmp_path: Path):
    store = ProviderRuntimeStateStore(tmp_path / "provider-resilience.sqlite3")
    google = profile("google", 1, daily=1)
    with store.reservation(google, now=0):
        pass
    assert store.candidate(google, now=1).daily_budget_remaining == 0
    assert store.candidate(google, now=86401).daily_budget_remaining == 1
