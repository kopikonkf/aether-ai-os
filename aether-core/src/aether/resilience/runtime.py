"""Persistent AETHER_HOME-owned provider state and governed runtime dispatch."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Generic, Iterable, TypeVar

from .provider import (
    CircuitState,
    ProviderCandidate,
    ProviderErrorKind,
    ProviderErrorSignal,
    classify_provider_error,
    fallback_eligible_error,
    select_fallback,
)

T = TypeVar("T")


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    priority: int
    capabilities: frozenset[str]
    daily_limit: int
    concurrency_limit: int
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0
    data_policy_tags: frozenset[str] = frozenset()
    enabled: bool = True


class ProviderRuntimeStateStore:
    """SQLite authority for budget, concurrency, circuit, and routing receipts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_state (
                    provider_id TEXT PRIMARY KEY,
                    day_key TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0 CHECK(consumed >= 0),
                    in_flight INTEGER NOT NULL DEFAULT 0 CHECK(in_flight >= 0),
                    circuit_state TEXT NOT NULL DEFAULT 'closed',
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    opened_at REAL,
                    cooldown_until REAL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provider_runtime_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    provider_id TEXT,
                    receipt_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def day_key(now: float) -> str:
        return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()

    def _ensure(self, db: sqlite3.Connection, provider_id: str, now: float) -> sqlite3.Row:
        day_key = self.day_key(now)
        db.execute(
            """
            INSERT OR IGNORE INTO provider_state(provider_id, day_key, updated_at)
            VALUES (?, ?, ?)
            """,
            (provider_id, day_key, now),
        )
        row = db.execute(
            "SELECT * FROM provider_state WHERE provider_id = ?", (provider_id,)
        ).fetchone()
        assert row is not None
        if row["day_key"] != day_key:
            db.execute(
                """
                UPDATE provider_state
                SET day_key = ?, consumed = 0, updated_at = ?
                WHERE provider_id = ?
                """,
                (day_key, now, provider_id),
            )
            row = db.execute(
                "SELECT * FROM provider_state WHERE provider_id = ?", (provider_id,)
            ).fetchone()
        return row

    def candidate(self, profile: ProviderProfile, *, now: float) -> ProviderCandidate:
        with self._lock, self._connect() as db:
            row = self._ensure(db, profile.provider_id, now)
            state = CircuitState(row["circuit_state"])
            cooldown_until = row["cooldown_until"]
            if state is CircuitState.OPEN and cooldown_until is not None and now >= cooldown_until:
                state = CircuitState.HALF_OPEN
            return ProviderCandidate(
                provider_id=profile.provider_id,
                priority=profile.priority,
                capabilities=profile.capabilities,
                enabled=profile.enabled,
                daily_budget_remaining=max(0, profile.daily_limit - row["consumed"]),
                concurrency_available=max(0, profile.concurrency_limit - row["in_flight"]),
                circuit_state=state,
                cooldown_until=cooldown_until if state is CircuitState.OPEN else None,
                data_policy_tags=profile.data_policy_tags,
            )

    @contextmanager
    def reservation(self, profile: ProviderProfile, *, now: float):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._ensure(db, profile.provider_id, now)
            if row["consumed"] >= profile.daily_limit:
                db.execute("ROLLBACK")
                raise RuntimeError(f"daily budget exhausted for {profile.provider_id}")
            if row["in_flight"] >= profile.concurrency_limit:
                db.execute("ROLLBACK")
                raise RuntimeError(f"concurrency exhausted for {profile.provider_id}")
            db.execute(
                """
                UPDATE provider_state
                SET consumed = consumed + 1, in_flight = in_flight + 1, updated_at = ?
                WHERE provider_id = ?
                """,
                (now, profile.provider_id),
            )
            db.execute("COMMIT")
        try:
            yield
        finally:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = self._ensure(db, profile.provider_id, now)
                db.execute(
                    """
                    UPDATE provider_state
                    SET in_flight = MAX(0, in_flight - 1), updated_at = ?
                    WHERE provider_id = ?
                    """,
                    (now, profile.provider_id),
                )
                db.execute("COMMIT")

    def record_success(self, profile: ProviderProfile, *, now: float) -> None:
        with self._lock, self._connect() as db:
            self._ensure(db, profile.provider_id, now)
            db.execute(
                """
                UPDATE provider_state
                SET circuit_state = 'closed', consecutive_failures = 0,
                    opened_at = NULL, cooldown_until = NULL, updated_at = ?
                WHERE provider_id = ?
                """,
                (now, profile.provider_id),
            )

    def record_failure(
        self, profile: ProviderProfile, kind: ProviderErrorKind, *, now: float
    ) -> None:
        if kind in {ProviderErrorKind.INVALID_REQUEST, ProviderErrorKind.UNKNOWN}:
            return
        with self._lock, self._connect() as db:
            row = self._ensure(db, profile.provider_id, now)
            failures = int(row["consecutive_failures"]) + 1
            should_open = (
                row["circuit_state"] == CircuitState.HALF_OPEN.value
                or failures >= profile.failure_threshold
            )
            db.execute(
                """
                UPDATE provider_state
                SET consecutive_failures = ?, circuit_state = ?,
                    opened_at = ?, cooldown_until = ?, updated_at = ?
                WHERE provider_id = ?
                """,
                (
                    failures,
                    CircuitState.OPEN.value if should_open else row["circuit_state"],
                    now if should_open else row["opened_at"],
                    now + profile.cooldown_seconds if should_open else row["cooldown_until"],
                    now,
                    profile.provider_id,
                ),
            )

    def append_receipt(
        self, receipt_id: str, provider_id: str | None, receipt_type: str, payload: dict, *, now: float
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO provider_runtime_receipts
                (receipt_id, provider_id, receipt_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    provider_id,
                    receipt_type,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    now,
                ),
            )


class ResilientProviderRouter(Generic[T]):
    """Capability-aware dispatch with persistent budget/circuit state."""

    def __init__(
        self,
        profiles: Iterable[ProviderProfile],
        store: ProviderRuntimeStateStore,
        *,
        clock: Callable[[], float],
    ) -> None:
        self.profiles = {profile.provider_id: profile for profile in profiles}
        self.store = store
        self.clock = clock

    def invoke(
        self,
        *,
        capability: str,
        allowed_data_policy_tags: Iterable[str],
        operation: Callable[[str], T],
        error_signal: Callable[[Exception], ProviderErrorSignal],
    ) -> T:
        remaining = set(self.profiles)
        while remaining:
            now = self.clock()
            decision = select_fallback(
                [
                    self.store.candidate(self.profiles[provider_id], now=now)
                    for provider_id in remaining
                ],
                required_capabilities={capability},
                allowed_data_policy_tags=allowed_data_policy_tags,
                now=now,
            )
            self.store.append_receipt(
                decision.decision_id,
                decision.selected_provider_id,
                "fallback-decision",
                {
                    "selected_provider_id": decision.selected_provider_id,
                    "evaluations": [asdict(value) for value in decision.evaluations],
                },
                now=now,
            )
            if decision.selected_provider_id is None:
                break
            profile = self.profiles[decision.selected_provider_id]
            try:
                with self.store.reservation(profile, now=now):
                    result = operation(profile.provider_id)
            except Exception as error:
                kind = classify_provider_error(error_signal(error))
                self.store.record_failure(profile, kind, now=self.clock())
                if not fallback_eligible_error(kind):
                    raise
                remaining.remove(profile.provider_id)
                continue
            self.store.record_success(profile, now=self.clock())
            return result
        raise RuntimeError(f"no eligible provider for capability {capability}")
