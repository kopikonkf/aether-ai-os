"""Provider-neutral contracts for scheduled runtime fleet operations.

The scheduler and native UI live outside Aether Core. Core owns only the
stable vocabulary used to describe jobs, incidents, budgets, and run receipts.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from aether.utils.ids import new_id


class FleetJobKind(StrEnum):
    HEALTH_PROBE = "health-probe"
    RECEIPT_RENEWAL = "receipt-renewal"
    BUDGET_EVALUATION = "budget-evaluation"
    INCIDENT_SWEEP = "incident-sweep"


class FleetJobState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class FleetRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FleetIncidentKind(StrEnum):
    CLI_UNAVAILABLE = "cli-unavailable"
    AUTHENTICATION_FAILED = "authentication-failed"
    CONFORMANCE_MISSING = "conformance-missing"
    CONFORMANCE_EXPIRED = "conformance-expired"
    CONFORMANCE_STALE = "conformance-stale"
    RECEIPT_RENEWAL_DUE = "receipt-renewal-due"
    RATE_LIMITED = "rate-limited"
    QUOTA_EXHAUSTED = "quota-exhausted"
    RELIABILITY_DEGRADED = "reliability-degraded"
    INVOCATION_BUDGET_EXCEEDED = "invocation-budget-exceeded"
    COST_BUDGET_EXCEEDED = "cost-budget-exceeded"
    NO_ROUTABLE_DRIVER = "no-routable-driver"
    SCHEDULE_FAILURE = "schedule-failure"


class FleetIncidentSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class FleetIncidentState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class RuntimeFleetBudgetPolicy:
    daily_invocation_limit: int = 200
    daily_cost_limit_usd: float = 10.0
    minimum_reliability_score: float = 0.35
    maximum_consecutive_failures: int = 3
    maximum_fallback_attempts: int = 3
    retry_cooldown_seconds: int = 300
    cee_trigger_min_occurrences: int = 2
    cee_trigger_severities: tuple[FleetIncidentSeverity, ...] = (
        FleetIncidentSeverity.HIGH,
        FleetIncidentSeverity.CRITICAL,
    )

    def validate(self) -> None:
        if self.daily_invocation_limit < 1:
            raise ValueError("daily_invocation_limit must be positive")
        if self.daily_cost_limit_usd < 0:
            raise ValueError("daily_cost_limit_usd cannot be negative")
        if not 0 <= self.minimum_reliability_score <= 1:
            raise ValueError("minimum_reliability_score must be between 0 and 1")
        if self.maximum_consecutive_failures < 1 or self.maximum_fallback_attempts < 1:
            raise ValueError("failure and fallback bounds must be positive")


@dataclass(frozen=True)
class ScheduledFleetJob:
    kind: FleetJobKind
    interval_seconds: int
    state: FleetJobState = FleetJobState.ACTIVE
    next_run_at: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: new_id("fleet-job"))
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> None:
        if self.interval_seconds < 5:
            raise ValueError("fleet job interval must be at least 5 seconds")


@dataclass(frozen=True)
class FleetRunReceipt:
    job_id: str
    kind: FleetJobKind
    status: FleetRunStatus
    started_at: str
    completed_at: str | None = None
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: new_id("fleet-run"))


@dataclass(frozen=True)
class RuntimeFleetIncident:
    kind: FleetIncidentKind
    severity: FleetIncidentSeverity
    summary: str
    fingerprint: str
    driver_id: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    incident_id: str = field(default_factory=lambda: new_id("fleet-incident"))
    first_seen_at: str = ""
    last_seen_at: str = ""
    occurrence_count: int = 1
    state: FleetIncidentState = FleetIncidentState.OPEN
    cee_trigger_id: str | None = None


@dataclass(frozen=True)
class RuntimeFleetBudgetSnapshot:
    window_start: str
    window_end: str
    invocation_count: int
    invocation_limit: int
    known_cost_usd: float
    cost_limit_usd: float
    unknown_cost_invocations: int
    invocation_budget_exceeded: bool
    cost_budget_exceeded: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


def fleet_incident_fingerprint(
    *,
    kind: FleetIncidentKind,
    driver_id: str | None,
    summary: str,
    details: Mapping[str, Any] | None = None,
) -> str:
    """Return a stable semantic fingerprint without embedding secret values."""
    payload = {
        "kind": kind.value,
        "driver_id": (driver_id or "").strip().casefold(),
        "summary": " ".join(summary.casefold().split()),
        "details": dict(details or {}),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
