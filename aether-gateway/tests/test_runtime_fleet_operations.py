from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from aether.contracts import (
    FleetIncidentKind,
    FleetIncidentState,
    FleetIncidentSeverity,
    FleetJobKind,
    RuntimeConformanceState,
    RuntimeDriverAvailability,
    RuntimeFleetIncident,
    RuntimeQuotaState,
)
from aether_gateway.runtime_operations import FleetOperationsStore, RuntimeFleetOperationsService, RuntimeFleetScheduler


class FakeTelemetry:
    def __init__(self, invocations=()):
        self.invocations = tuple(invocations)

    def list_invocations(self, *, adapter_id=None, limit=100):
        values = self.invocations
        if adapter_id:
            values = tuple(item for item in values if item.get("adapter_id") == adapter_id)
        return values[:limit]

    def status(self):
        return {"invocations": len(self.invocations), "progress_events": 0}


class FakeDriverPack:
    def __init__(self):
        self.renew_calls = 0
        self.driver = {
            "driver_id": "gemini",
            "availability": RuntimeDriverAvailability.UNAVAILABLE.value,
            "conformance_state": RuntimeConformanceState.MISSING.value,
            "routing_eligible": False,
            "runtime_version": None,
            "model_id": "fixture",
            "provider_id": "fixture",
            "reliability": {
                "score": 0.2,
                "consecutive_failures": 4,
                "effective_priority_penalty": 20,
            },
            "quota_state": RuntimeQuotaState.UNAVAILABLE.value,
            "receipt_id": None,
            "receipt_expires_at": None,
            "renewal_due": True,
            "reason": "fixture unavailable",
            "metadata": {"display_name": "Gemini fixture", "priority": 3, "auth_ready": False},
        }

    def operations_console(self):
        return {
            "routing_eligible_count": 0,
            "renewal_due_count": 1,
            "drivers": [dict(self.driver)],
            "telemetry": {},
        }

    async def renew_due_receipts(self, *, principal, ttl_hours=None):
        self.renew_calls += 1
        return ()


class FakeEvolutionEngine:
    def __init__(self):
        self.triggers = []

    def register_trigger(self, trigger):
        self.triggers.append(trigger)
        return trigger


def _policy(**budget_overrides):
    return {
        "policy_id": "test.fleet",
        "scheduler": {
            "poll_interval_seconds": 1,
            "jobs": {kind.value: {"interval_seconds": 5, "enabled": True} for kind in FleetJobKind},
        },
        "budgets": {
            "daily_invocation_limit": budget_overrides.get("daily_invocation_limit", 2),
            "daily_cost_limit_usd": budget_overrides.get("daily_cost_limit_usd", 1.0),
            "minimum_reliability_score": 0.35,
            "maximum_consecutive_failures": 3,
            "unknown_cost_is_zero": False,
        },
        "fallback": {
            "maximum_attempts": 3,
            "retry_cooldown_seconds": 300,
            "do_not_retry_same_fingerprint_without_reason": True,
            "stop_on_pending_approval": True,
        },
        "receipt_renewal": {
            "queue_only_by_default": True,
            "auto_renew_environment_flag": "AETHER_FLEET_AUTO_RENEW",
            "renewal_ttl_hours": 24,
        },
        "incidents": {
            "cee_trigger_min_occurrences": 2,
            "cee_trigger_severities": ["high", "critical"],
        },
    }


def test_store_persists_jobs_runs_incidents_and_append_only_transitions(tmp_path: Path):
    store = FleetOperationsStore(tmp_path / "fleet.sqlite3")
    service = RuntimeFleetOperationsService(FakeDriverPack(), FakeTelemetry(), store, policy=_policy())
    assert {job.kind for job in store.list_jobs()} == set(FleetJobKind)
    updated = service.update_job(FleetJobKind.HEALTH_PROBE, principal="founder", enabled=False, interval_seconds=30)
    assert updated.interval_seconds == 30
    assert updated.state.value == "paused"

    incident = store.open_incident(RuntimeFleetIncident(
        kind=FleetIncidentKind.NO_ROUTABLE_DRIVER,
        severity=FleetIncidentSeverity.CRITICAL,
        summary="No runtime",
        fingerprint="fixture-fingerprint",
        evidence={"managed_by": "test"},
    ))
    acknowledged = store.transition_incident(
        incident.incident_id,
        FleetIncidentState.ACKNOWLEDGED,
        principal="founder",
        reason="reviewing",
    )
    assert acknowledged.state == FleetIncidentState.ACKNOWLEDGED
    with sqlite3.connect(store.path) as conn:
        transition_id = conn.execute("SELECT transition_id FROM fleet_incident_transitions LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE fleet_incident_transitions SET principal='model' WHERE transition_id=?", (transition_id,))


def test_health_budget_queue_and_cee_trigger_are_bounded(tmp_path: Path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    telemetry = FakeTelemetry((
        {"adapter_id": "runtime.coding.gemini", "created_at": now, "payload": {"cost_usd": 0.7}},
        {"adapter_id": "runtime.coding.gemini", "created_at": now, "payload": {"estimated_cost_usd": 0.6}},
        {"adapter_id": "runtime.coding.gemini", "created_at": now, "payload": {}},
    ))
    pack = FakeDriverPack()
    evolution = FakeEvolutionEngine()
    store = FleetOperationsStore(tmp_path / "fleet.sqlite3")
    service = RuntimeFleetOperationsService(pack, telemetry, store, evolution_engine=evolution, policy=_policy())

    asyncio.run(service.run_job(FleetJobKind.HEALTH_PROBE, principal="founder"))
    asyncio.run(service.run_job(FleetJobKind.HEALTH_PROBE, principal="founder"))
    asyncio.run(service.run_job(FleetJobKind.BUDGET_EVALUATION, principal="founder"))
    renewal = asyncio.run(service.run_job(FleetJobKind.RECEIPT_RENEWAL, principal="founder"))
    assert renewal["metadata"]["mode"] == "queue-only"
    assert pack.renew_calls == 0

    sweep = asyncio.run(service.run_job(FleetJobKind.INCIDENT_SWEEP, principal="founder"))
    assert sweep["metadata"]["cee_trigger_count"] >= 1
    assert evolution.triggers
    assert all(item.metadata["authority"] == "learning-trigger-only" for item in evolution.triggers)

    snapshot = service.snapshot()
    kinds = {item["kind"] for item in snapshot["incidents"] if item["state"] != "resolved"}
    assert FleetIncidentKind.NO_ROUTABLE_DRIVER.value in kinds
    assert FleetIncidentKind.INVOCATION_BUDGET_EXCEEDED.value in kinds
    assert FleetIncidentKind.COST_BUDGET_EXCEEDED.value in kinds
    assert FleetIncidentKind.RECEIPT_RENEWAL_DUE.value in kinds
    assert snapshot["budget"]["unknown_cost_invocations"] == 1
    assert snapshot["fallback_policy"]["maximum_attempts"] == 3

    monkeypatch.setenv("AETHER_FLEET_AUTO_RENEW", "true")
    asyncio.run(service.run_job(FleetJobKind.RECEIPT_RENEWAL, principal="founder"))
    assert pack.renew_calls == 1


def test_scheduler_is_nonfatal_and_reports_state(tmp_path: Path):
    store = FleetOperationsStore(tmp_path / "fleet.sqlite3")
    service = RuntimeFleetOperationsService(FakeDriverPack(), FakeTelemetry(), store, policy=_policy())
    for job in store.list_jobs():
        store.update_job(job.kind, next_run_at="2000-01-01T00:00:00+00:00", principal="test")
    scheduler = RuntimeFleetScheduler(service, poll_interval_seconds=1, enabled=True)
    runs = asyncio.run(scheduler.run_once())
    assert len(runs) == 4
    status = scheduler.status()
    assert status["cycles"] == 1
    assert status["last_error"] is None
