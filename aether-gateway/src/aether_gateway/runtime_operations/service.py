"""Scheduled runtime fleet operations owned by the Aether backend."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from typing import Any, Mapping, Sequence

import yaml

from aether.contracts import (
    EventType,
    EvolutionTrigger,
    EvolutionTriggerType,
    FleetIncidentKind,
    FleetIncidentSeverity,
    FleetIncidentState,
    FleetJobKind,
    FleetJobState,
    FleetRunStatus,
    RuntimeConformanceState,
    RuntimeDriverAvailability,
    RuntimeFleetBudgetPolicy,
    RuntimeFleetBudgetSnapshot,
    RuntimeFleetIncident,
    RuntimeQuotaState,
    ScheduledFleetJob,
    fleet_incident_fingerprint,
)
from aether.events import EventBus

from .store import FleetOperationsStore, utc_now_iso


def load_fleet_policy() -> dict[str, Any]:
    path = files("aether.runtimes").joinpath("runtime_fleet_operations.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class RuntimeFleetOperationsService:
    """Coordinates observations, schedules, incidents, budgets, and CEE intake.

    It never approves coding actions. Scheduled receipt renewal is queue-only by
    default; automatic renewal must be explicitly enabled by an environment flag.
    """

    def __init__(
        self,
        driver_pack,
        telemetry,
        store: FleetOperationsStore,
        *,
        evolution_engine=None,
        event_bus: EventBus | None = None,
        policy: Mapping[str, Any] | None = None,
    ) -> None:
        self.driver_pack = driver_pack
        self.telemetry = telemetry
        self.store = store
        self.evolution_engine = evolution_engine
        self.event_bus = event_bus
        self.policy = dict(policy or load_fleet_policy())
        budgets = self.policy.get("budgets", {})
        fallback = self.policy.get("fallback", {})
        incidents = self.policy.get("incidents", {})
        self.budget_policy = RuntimeFleetBudgetPolicy(
            daily_invocation_limit=int(budgets.get("daily_invocation_limit", 200)),
            daily_cost_limit_usd=float(budgets.get("daily_cost_limit_usd", 10.0)),
            minimum_reliability_score=float(budgets.get("minimum_reliability_score", 0.35)),
            maximum_consecutive_failures=int(budgets.get("maximum_consecutive_failures", 3)),
            maximum_fallback_attempts=int(fallback.get("maximum_attempts", 3)),
            retry_cooldown_seconds=int(fallback.get("retry_cooldown_seconds", 300)),
            cee_trigger_min_occurrences=int(incidents.get("cee_trigger_min_occurrences", 2)),
            cee_trigger_severities=tuple(
                FleetIncidentSeverity(item)
                for item in incidents.get("cee_trigger_severities", ["high", "critical"])
            ),
        )
        self.budget_policy.validate()
        self._lock = asyncio.Lock()
        self._bootstrap_jobs()

    def _bootstrap_jobs(self) -> None:
        now = datetime.now(timezone.utc)
        jobs = self.policy.get("scheduler", {}).get("jobs", {})
        for kind in FleetJobKind:
            raw = jobs.get(kind.value, {})
            interval = max(5, int(raw.get("interval_seconds", 300)))
            self.store.ensure_job(
                kind,
                interval_seconds=interval,
                enabled=bool(raw.get("enabled", True)),
                next_run_at=_as_iso(now + timedelta(seconds=interval)),
                metadata={"policy_id": self.policy.get("policy_id"), **dict(raw)},
            )

    # ---- public console ------------------------------------------------
    def snapshot(self) -> Mapping[str, Any]:
        console = self.driver_pack.operations_console()
        budget = self._budget_snapshot()
        incidents = self.store.list_incidents(limit=500)
        open_incidents = [item for item in incidents if item.state != FleetIncidentState.RESOLVED]
        jobs = self.store.list_jobs()
        runs = self.store.list_runs(limit=100)
        highest = self._highest_severity(open_incidents)
        return {
            "policy_id": self.policy.get("policy_id"),
            "generated_at": utc_now_iso(),
            "fleet_state": "critical" if highest == FleetIncidentSeverity.CRITICAL else (
                "degraded" if highest in {FleetIncidentSeverity.HIGH, FleetIncidentSeverity.WARNING} else "healthy"
            ),
            "routing_eligible_count": console.get("routing_eligible_count", 0),
            "renewal_due_count": console.get("renewal_due_count", 0),
            "drivers": console.get("drivers", []),
            "telemetry": console.get("telemetry", {}),
            "jobs": [self._job_dict(item) for item in jobs],
            "recent_runs": [self._run_dict(item) for item in runs],
            "incidents": [self._incident_dict(item) for item in incidents],
            "open_incident_count": len(open_incidents),
            "critical_incident_count": sum(item.severity == FleetIncidentSeverity.CRITICAL for item in open_incidents),
            "budget": self._budget_dict(budget),
            "fallback_policy": {
                "maximum_attempts": self.budget_policy.maximum_fallback_attempts,
                "retry_cooldown_seconds": self.budget_policy.retry_cooldown_seconds,
                "same_fingerprint_requires_reason": bool(
                    self.policy.get("fallback", {}).get("do_not_retry_same_fingerprint_without_reason", True)
                ),
                "stop_on_pending_approval": bool(self.policy.get("fallback", {}).get("stop_on_pending_approval", True)),
            },
            "receipt_renewal_mode": "automatic" if self._auto_renew_enabled() else "queue-only",
            "store": self.store.status(),
            "secret_values_exposed": False,
        }

    async def run_due(self, *, principal: str = "aether.fleet-scheduler", now: datetime | None = None) -> tuple[Mapping[str, Any], ...]:
        async with self._lock:
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            self._emit(EventType.RUNTIME_FLEET_CYCLE_STARTED, {
                "principal": principal,
                "at": _as_iso(current),
            })
            results: list[Mapping[str, Any]] = []
            for job in self.store.due_jobs(_as_iso(current)):
                results.append(await self._run_job_locked(job, principal=principal, now=current))
            self._emit(EventType.RUNTIME_FLEET_CYCLE_COMPLETED, {
                "principal": principal,
                "at": _as_iso(current),
                "run_count": len(results),
                "failed_count": sum(item["status"] == FleetRunStatus.FAILED.value for item in results),
            })
            return tuple(results)

    async def run_job(self, kind: FleetJobKind, *, principal: str, now: datetime | None = None) -> Mapping[str, Any]:
        async with self._lock:
            return await self._run_job_locked(
                self.store.get_job(kind),
                principal=principal,
                now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc),
            )

    def update_job(
        self,
        kind: FleetJobKind,
        *,
        principal: str,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
        run_immediately: bool = False,
    ) -> ScheduledFleetJob:
        current = self.store.get_job(kind)
        state = None if enabled is None else (FleetJobState.ACTIVE if enabled else FleetJobState.PAUSED)
        next_run = utc_now_iso() if run_immediately else None
        updated = self.store.update_job(
            kind,
            interval_seconds=interval_seconds,
            state=state,
            next_run_at=next_run,
            principal=principal,
        )
        self._emit(EventType.RUNTIME_FLEET_SCHEDULE_UPDATED, {
            "job_id": updated.job_id,
            "kind": updated.kind.value,
            "state": updated.state.value,
            "interval_seconds": updated.interval_seconds,
            "next_run_at": updated.next_run_at,
            "principal": principal,
        })
        return updated

    def acknowledge_incident(self, incident_id: str, *, principal: str, reason: str) -> RuntimeFleetIncident:
        incident = self.store.transition_incident(
            incident_id,
            FleetIncidentState.ACKNOWLEDGED,
            principal=principal,
            reason=reason,
        )
        self._emit(EventType.RUNTIME_FLEET_INCIDENT_ACKNOWLEDGED, {
            "incident_id": incident.incident_id,
            "fingerprint": incident.fingerprint,
            "principal": principal,
            "reason": reason,
        })
        return incident

    def resolve_incident(self, incident_id: str, *, principal: str, reason: str) -> RuntimeFleetIncident:
        incident = self.store.transition_incident(
            incident_id,
            FleetIncidentState.RESOLVED,
            principal=principal,
            reason=reason,
        )
        self._emit(EventType.RUNTIME_FLEET_INCIDENT_RESOLVED, {
            "incident_id": incident.incident_id,
            "fingerprint": incident.fingerprint,
            "principal": principal,
            "reason": reason,
        })
        return incident

    def record_cost(
        self,
        *,
        driver_id: str,
        task_id: str | None,
        cost_usd: float | None,
        input_tokens: int | None,
        output_tokens: int | None,
        source: str,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        return self.store.record_cost(
            driver_id=driver_id,
            task_id=task_id,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            source=source,
            payload=payload,
        )

    # ---- job execution -------------------------------------------------
    async def _run_job_locked(self, job: ScheduledFleetJob, *, principal: str, now: datetime) -> Mapping[str, Any]:
        receipt = self.store.start_run(job)
        self._emit(EventType.RUNTIME_FLEET_JOB_DUE, {
            "run_id": receipt.run_id,
            "job_id": job.job_id,
            "kind": job.kind.value,
            "principal": principal,
        })
        status = FleetRunStatus.COMPLETED
        summary = "completed"
        metadata: Mapping[str, Any] = {}
        try:
            if job.state != FleetJobState.ACTIVE and principal == "aether.fleet-scheduler":
                status = FleetRunStatus.SKIPPED
                summary = "job is paused"
            elif job.kind == FleetJobKind.HEALTH_PROBE:
                metadata = self._health_probe(principal=principal)
                summary = f"probed {metadata['driver_count']} drivers"
            elif job.kind == FleetJobKind.RECEIPT_RENEWAL:
                metadata = await self._receipt_renewal(principal=principal)
                summary = f"queued {metadata['queued_count']} receipt renewals"
            elif job.kind == FleetJobKind.BUDGET_EVALUATION:
                metadata = self._budget_evaluation(principal=principal)
                summary = "runtime budget evaluated"
            elif job.kind == FleetJobKind.INCIDENT_SWEEP:
                metadata = self._incident_sweep(principal=principal)
                summary = f"swept {metadata['incident_count']} incidents"
            else:
                status = FleetRunStatus.SKIPPED
                summary = f"unsupported job kind: {job.kind.value}"
        except Exception as exc:
            status = FleetRunStatus.FAILED
            summary = f"{type(exc).__name__}: {exc}"
            metadata = {"error_type": type(exc).__name__, "error": str(exc)}
            self._open_condition(
                kind=FleetIncidentKind.SCHEDULE_FAILURE,
                severity=FleetIncidentSeverity.HIGH,
                summary=f"Fleet job {job.kind.value} failed: {type(exc).__name__}",
                driver_id=None,
                details={"job_id": job.job_id, "job_kind": job.kind.value, "error_type": type(exc).__name__},
                managed_by="scheduler",
                principal=principal,
            )
        next_run = now + timedelta(seconds=job.interval_seconds)
        self.store.mark_job_scheduled(job.job_id, next_run_at=_as_iso(next_run), principal=principal)
        final = self.store.finish_run(receipt.run_id, status=status, summary=summary, metadata=metadata)
        self._emit(
            EventType.RUNTIME_FLEET_JOB_COMPLETED if status in {FleetRunStatus.COMPLETED, FleetRunStatus.SKIPPED} else EventType.RUNTIME_FLEET_JOB_FAILED,
            self._run_dict(final),
            severity="warning" if status == FleetRunStatus.FAILED else "info",
        )
        return self._run_dict(final)

    def _health_probe(self, *, principal: str) -> Mapping[str, Any]:
        console = self.driver_pack.operations_console()
        active: list[str] = []
        opened = 0
        for driver in console.get("drivers", []):
            driver_id = str(driver["driver_id"])
            availability = RuntimeDriverAvailability(str(driver["availability"]))
            conformance = RuntimeConformanceState(str(driver["conformance_state"]))
            quota = RuntimeQuotaState(str(driver["quota_state"]))
            reliability = driver.get("reliability") or {}
            if availability in {RuntimeDriverAvailability.UNAVAILABLE, RuntimeDriverAvailability.DISABLED}:
                active.append(self._open_condition(
                    kind=FleetIncidentKind.CLI_UNAVAILABLE,
                    severity=FleetIncidentSeverity.WARNING,
                    summary=f"{driver_id} is not available",
                    driver_id=driver_id,
                    details={"availability": availability.value, "reason": driver.get("reason")},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
            if quota == RuntimeQuotaState.AUTHENTICATION_FAILED:
                active.append(self._open_condition(
                    kind=FleetIncidentKind.AUTHENTICATION_FAILED,
                    severity=FleetIncidentSeverity.HIGH,
                    summary=f"{driver_id} authentication is not ready",
                    driver_id=driver_id,
                    details={"quota_state": quota.value},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
            elif quota == RuntimeQuotaState.RATE_LIMITED:
                active.append(self._open_condition(
                    kind=FleetIncidentKind.RATE_LIMITED,
                    severity=FleetIncidentSeverity.WARNING,
                    summary=f"{driver_id} is rate limited",
                    driver_id=driver_id,
                    details={"quota_state": quota.value},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
            elif quota == RuntimeQuotaState.QUOTA_EXHAUSTED:
                active.append(self._open_condition(
                    kind=FleetIncidentKind.QUOTA_EXHAUSTED,
                    severity=FleetIncidentSeverity.HIGH,
                    summary=f"{driver_id} quota is exhausted",
                    driver_id=driver_id,
                    details={"quota_state": quota.value},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
            conformance_map = {
                RuntimeConformanceState.MISSING: (FleetIncidentKind.CONFORMANCE_MISSING, FleetIncidentSeverity.WARNING),
                RuntimeConformanceState.EXPIRED: (FleetIncidentKind.CONFORMANCE_EXPIRED, FleetIncidentSeverity.HIGH),
                RuntimeConformanceState.STALE: (FleetIncidentKind.CONFORMANCE_STALE, FleetIncidentSeverity.HIGH),
                RuntimeConformanceState.FAILED: (FleetIncidentKind.CONFORMANCE_STALE, FleetIncidentSeverity.HIGH),
            }
            if conformance in conformance_map and availability != RuntimeDriverAvailability.DISABLED:
                kind, severity = conformance_map[conformance]
                active.append(self._open_condition(
                    kind=kind,
                    severity=severity,
                    summary=f"{driver_id} conformance is {conformance.value}",
                    driver_id=driver_id,
                    details={"conformance_state": conformance.value},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
            score = float(reliability.get("score", 0.5))
            consecutive = int(reliability.get("consecutive_failures", 0))
            if score < self.budget_policy.minimum_reliability_score or consecutive >= self.budget_policy.maximum_consecutive_failures:
                active.append(self._open_condition(
                    kind=FleetIncidentKind.RELIABILITY_DEGRADED,
                    severity=FleetIncidentSeverity.HIGH if consecutive >= self.budget_policy.maximum_consecutive_failures else FleetIncidentSeverity.WARNING,
                    summary=f"{driver_id} reliability is degraded",
                    driver_id=driver_id,
                    details={"score": score, "consecutive_failures": consecutive},
                    managed_by="health-probe",
                    principal=principal,
                ).fingerprint)
                opened += 1
        if int(console.get("routing_eligible_count", 0)) == 0:
            active.append(self._open_condition(
                kind=FleetIncidentKind.NO_ROUTABLE_DRIVER,
                severity=FleetIncidentSeverity.CRITICAL,
                summary="No conformed and healthy live coding driver is routable",
                driver_id=None,
                details={"driver_count": len(console.get("drivers", []))},
                managed_by="health-probe",
                principal=principal,
            ).fingerprint)
            opened += 1
        resolved = self.store.resolve_absent(
            active,
            principal=principal,
            reason="health condition cleared",
            managed_by="health-probe",
        )
        for incident in resolved:
            self._emit(EventType.RUNTIME_FLEET_INCIDENT_RESOLVED, self._incident_dict(incident))
        return {
            "driver_count": len(console.get("drivers", [])),
            "routing_eligible_count": int(console.get("routing_eligible_count", 0)),
            "active_condition_count": len(active),
            "opened_or_observed_count": opened,
            "resolved_count": len(resolved),
        }

    async def _receipt_renewal(self, *, principal: str) -> Mapping[str, Any]:
        console = self.driver_pack.operations_console()
        due = [item for item in console.get("drivers", []) if item.get("renewal_due")]
        renewed: Sequence[Any] = ()
        queued: list[str] = []
        if self._auto_renew_enabled():
            renewed = await self.driver_pack.renew_due_receipts(
                principal="aether.fleet-scheduler",
                ttl_hours=int(self.policy.get("receipt_renewal", {}).get("renewal_ttl_hours", 24)),
            )
        renewed_ids = {item.driver_id for item in renewed}
        active: list[str] = []
        for item in due:
            driver_id = str(item["driver_id"])
            if driver_id in renewed_ids:
                continue
            incident = self._open_condition(
                kind=FleetIncidentKind.RECEIPT_RENEWAL_DUE,
                severity=FleetIncidentSeverity.WARNING,
                summary=f"{driver_id} conformance receipt requires operator renewal",
                driver_id=driver_id,
                details={
                    "receipt_id": item.get("receipt_id"),
                    "receipt_expires_at": item.get("receipt_expires_at"),
                    "queue_only": not self._auto_renew_enabled(),
                },
                managed_by="receipt-renewal",
                principal=principal,
            )
            active.append(incident.fingerprint)
            queued.append(driver_id)
        resolved = self.store.resolve_absent(
            active,
            principal=principal,
            reason="receipt renewal no longer due",
            managed_by="receipt-renewal",
        )
        return {
            "due_count": len(due),
            "queued_count": len(queued),
            "queued_driver_ids": queued,
            "renewed_driver_ids": sorted(renewed_ids),
            "resolved_count": len(resolved),
            "mode": "automatic" if self._auto_renew_enabled() else "queue-only",
        }

    def _budget_evaluation(self, *, principal: str) -> Mapping[str, Any]:
        snapshot = self._budget_snapshot()
        active: list[str] = []
        if snapshot.invocation_budget_exceeded:
            incident = self._open_condition(
                kind=FleetIncidentKind.INVOCATION_BUDGET_EXCEEDED,
                severity=FleetIncidentSeverity.HIGH,
                summary="Daily runtime invocation budget exceeded",
                driver_id=None,
                details={"count": snapshot.invocation_count, "limit": snapshot.invocation_limit},
                managed_by="budget-evaluation",
                principal=principal,
            )
            active.append(incident.fingerprint)
        if snapshot.cost_budget_exceeded:
            incident = self._open_condition(
                kind=FleetIncidentKind.COST_BUDGET_EXCEEDED,
                severity=FleetIncidentSeverity.HIGH,
                summary="Daily known runtime cost budget exceeded",
                driver_id=None,
                details={"known_cost_usd": snapshot.known_cost_usd, "limit_usd": snapshot.cost_limit_usd},
                managed_by="budget-evaluation",
                principal=principal,
            )
            active.append(incident.fingerprint)
        resolved = self.store.resolve_absent(
            active,
            principal=principal,
            reason="runtime budget returned within policy",
            managed_by="budget-evaluation",
        )
        if active:
            self._emit(EventType.RUNTIME_FLEET_BUDGET_EXCEEDED, self._budget_dict(snapshot), severity="warning")
        return {**self._budget_dict(snapshot), "resolved_count": len(resolved)}

    def _incident_sweep(self, *, principal: str) -> Mapping[str, Any]:
        incidents = self.store.list_incidents(states=(FleetIncidentState.OPEN, FleetIncidentState.ACKNOWLEDGED), limit=1000)
        triggered: list[str] = []
        escalated: list[str] = []
        for incident in incidents:
            if incident.severity in {FleetIncidentSeverity.HIGH, FleetIncidentSeverity.CRITICAL}:
                escalated.append(incident.incident_id)
                self._emit(EventType.RUNTIME_FLEET_OPERATOR_ESCALATED, self._incident_dict(incident), severity="warning")
            if (
                self.evolution_engine is not None
                and incident.cee_trigger_id is None
                and incident.occurrence_count >= self.budget_policy.cee_trigger_min_occurrences
                and incident.severity in set(self.budget_policy.cee_trigger_severities)
            ):
                trigger = self.evolution_engine.register_trigger(EvolutionTrigger(
                    trigger_type=EvolutionTriggerType.FAILURE,
                    fingerprint=incident.fingerprint,
                    summary=f"Runtime fleet incident: {incident.summary}",
                    evidence_ids=(incident.incident_id,),
                    metadata={
                        "source": "runtime-fleet-operations",
                        "incident_id": incident.incident_id,
                        "incident_kind": incident.kind.value,
                        "severity": incident.severity.value,
                        "driver_id": incident.driver_id,
                        "occurrence_count": incident.occurrence_count,
                        "authority": "learning-trigger-only",
                    },
                ))
                self.store.mark_cee_trigger(incident.incident_id, trigger.trigger_id)
                triggered.append(trigger.trigger_id)
                self._emit(EventType.RUNTIME_FLEET_CEE_TRIGGERED, {
                    "incident_id": incident.incident_id,
                    "trigger_id": trigger.trigger_id,
                    "fingerprint": incident.fingerprint,
                    "authority": "candidate-generation-not-authorized",
                }, severity="warning")
        return {
            "incident_count": len(incidents),
            "operator_escalation_count": len(escalated),
            "cee_trigger_count": len(triggered),
            "cee_trigger_ids": triggered,
        }

    # ---- evidence helpers ---------------------------------------------
    def _budget_snapshot(self, now: datetime | None = None) -> RuntimeFleetBudgetSnapshot:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        invocations = []
        for item in self.telemetry.list_invocations(limit=5000):
            try:
                created = _parse_time(str(item["created_at"]))
            except (ValueError, KeyError):
                continue
            if start <= created < end:
                invocations.append(item)
        known_cost = 0.0
        unknown = 0
        for item in invocations:
            value = self._extract_cost(item.get("payload") or {})
            if value is None:
                unknown += 1
            else:
                known_cost += value
        durable_cost = self.store.cost_usage(start_at=_as_iso(start), end_at=_as_iso(end))
        known_cost += float(durable_cost["known_cost_usd"])
        unknown += int(durable_cost["unknown_cost_events"])
        invocation_count = len(invocations)
        return RuntimeFleetBudgetSnapshot(
            window_start=_as_iso(start),
            window_end=_as_iso(end),
            invocation_count=invocation_count,
            invocation_limit=self.budget_policy.daily_invocation_limit,
            known_cost_usd=round(known_cost, 8),
            cost_limit_usd=self.budget_policy.daily_cost_limit_usd,
            unknown_cost_invocations=unknown,
            invocation_budget_exceeded=invocation_count > self.budget_policy.daily_invocation_limit,
            cost_budget_exceeded=known_cost > self.budget_policy.daily_cost_limit_usd,
            metadata={
                "unknown_cost_is_zero": bool(self.policy.get("budgets", {}).get("unknown_cost_is_zero", False)),
                "durable_cost_events": durable_cost,
            },
        )

    @staticmethod
    def _extract_cost(payload: Mapping[str, Any]) -> float | None:
        candidates: list[Any] = [payload.get("cost_usd"), payload.get("estimated_cost_usd")]
        usage = payload.get("usage")
        if isinstance(usage, Mapping):
            candidates.extend((usage.get("cost_usd"), usage.get("estimated_cost_usd")))
        for value in candidates:
            if value is None:
                continue
            try:
                amount = float(value)
            except (TypeError, ValueError):
                continue
            if amount >= 0:
                return amount
        return None

    def _open_condition(
        self,
        *,
        kind: FleetIncidentKind,
        severity: FleetIncidentSeverity,
        summary: str,
        driver_id: str | None,
        details: Mapping[str, Any],
        managed_by: str,
        principal: str,
    ) -> RuntimeFleetIncident:
        safe_details = json.loads(json.dumps(dict(details), default=str))
        fingerprint = fleet_incident_fingerprint(
            kind=kind,
            driver_id=driver_id,
            summary=summary,
            details=safe_details,
        )
        before = self.store.incident_by_fingerprint(fingerprint)
        incident = self.store.open_incident(RuntimeFleetIncident(
            kind=kind,
            severity=severity,
            summary=summary,
            fingerprint=fingerprint,
            driver_id=driver_id,
            evidence={"managed_by": managed_by, **safe_details},
        ), principal=principal)
        if before is None or before.state == FleetIncidentState.RESOLVED:
            self._emit(EventType.RUNTIME_FLEET_INCIDENT_OPENED, self._incident_dict(incident), severity=severity.value)
            if severity in {FleetIncidentSeverity.HIGH, FleetIncidentSeverity.CRITICAL}:
                self._emit(EventType.RUNTIME_FLEET_OPERATOR_ESCALATED, self._incident_dict(incident), severity="warning")
        return incident

    def _auto_renew_enabled(self) -> bool:
        flag = str(self.policy.get("receipt_renewal", {}).get("auto_renew_environment_flag") or "AETHER_FLEET_AUTO_RENEW")
        return os.environ.get(flag, "false").strip().casefold() in {"1", "true", "yes", "on"}

    @staticmethod
    def _highest_severity(incidents: Sequence[RuntimeFleetIncident]) -> FleetIncidentSeverity | None:
        order = {
            FleetIncidentSeverity.INFO: 0,
            FleetIncidentSeverity.WARNING: 1,
            FleetIncidentSeverity.HIGH: 2,
            FleetIncidentSeverity.CRITICAL: 3,
        }
        return max((item.severity for item in incidents), key=order.get, default=None)

    @staticmethod
    def _job_dict(job: ScheduledFleetJob) -> Mapping[str, Any]:
        return {
            **asdict(job),
            "kind": job.kind.value,
            "state": job.state.value,
        }

    @staticmethod
    def _run_dict(run) -> Mapping[str, Any]:
        return {
            **asdict(run),
            "kind": run.kind.value,
            "status": run.status.value,
        }

    @staticmethod
    def _incident_dict(incident: RuntimeFleetIncident) -> Mapping[str, Any]:
        return {
            **asdict(incident),
            "kind": incident.kind.value,
            "severity": incident.severity.value,
            "state": incident.state.value,
        }

    @staticmethod
    def _budget_dict(snapshot: RuntimeFleetBudgetSnapshot) -> Mapping[str, Any]:
        return asdict(snapshot)

    def _emit(
        self,
        event_type: EventType,
        payload: Mapping[str, Any],
        *,
        severity: str = "info",
    ) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(
                event_type,
                actor="aether.runtime-fleet-operations",
                payload=dict(payload),
                severity=severity,
            )
