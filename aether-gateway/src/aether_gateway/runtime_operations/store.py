"""Durable state for Aether runtime fleet scheduling and incidents."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.contracts import (
    FleetIncidentKind,
    FleetIncidentSeverity,
    FleetIncidentState,
    FleetJobKind,
    FleetJobState,
    FleetRunReceipt,
    FleetRunStatus,
    RuntimeFleetIncident,
    ScheduledFleetJob,
)
from aether.utils.ids import new_id


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


class FleetOperationsStore:
    """SQLite-backed scheduler, incident, cost, and audit ledger.

    Job definitions are operator-managed mutable state. Runs, job events,
    incident transitions, and cost evidence are append-only.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS fleet_jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT UNIQUE NOT NULL,
                    interval_seconds INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_job_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_runs (
                    run_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    summary TEXT NOT NULL,
                    metadata TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_incidents (
                    incident_id TEXT PRIMARY KEY,
                    fingerprint TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    driver_id TEXT,
                    summary TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL,
                    cee_trigger_id TEXT
                );
                CREATE TABLE IF NOT EXISTS fleet_incident_transitions (
                    transition_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fleet_cost_events (
                    cost_event_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    task_id TEXT,
                    cost_usd REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    source TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS fleet_job_events_no_update BEFORE UPDATE ON fleet_job_events
                BEGIN SELECT RAISE(ABORT, 'fleet job events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_job_events_no_delete BEFORE DELETE ON fleet_job_events
                BEGIN SELECT RAISE(ABORT, 'fleet job events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_runs_no_delete BEFORE DELETE ON fleet_runs
                BEGIN SELECT RAISE(ABORT, 'fleet runs cannot be deleted'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_incident_transitions_no_update BEFORE UPDATE ON fleet_incident_transitions
                BEGIN SELECT RAISE(ABORT, 'incident transitions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_incident_transitions_no_delete BEFORE DELETE ON fleet_incident_transitions
                BEGIN SELECT RAISE(ABORT, 'incident transitions are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_cost_events_no_update BEFORE UPDATE ON fleet_cost_events
                BEGIN SELECT RAISE(ABORT, 'cost evidence is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS fleet_cost_events_no_delete BEFORE DELETE ON fleet_cost_events
                BEGIN SELECT RAISE(ABORT, 'cost evidence is append-only'); END;
                """
            )

    # ---- jobs ---------------------------------------------------------
    def ensure_job(
        self,
        kind: FleetJobKind,
        *,
        interval_seconds: int,
        enabled: bool,
        next_run_at: str,
        metadata: Mapping[str, Any] | None = None,
        principal: str = "aether.bootstrap",
    ) -> ScheduledFleetJob:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_jobs WHERE kind = ?", (kind.value,)).fetchone()
            if row is not None:
                return self._job_from_row(row)
            now = utc_now_iso()
            job = ScheduledFleetJob(
                kind=kind,
                interval_seconds=max(5, int(interval_seconds)),
                state=FleetJobState.ACTIVE if enabled else FleetJobState.PAUSED,
                next_run_at=next_run_at,
                metadata=dict(metadata or {}),
                created_at=now,
                updated_at=now,
            )
            job.validate()
            conn.execute(
                "INSERT INTO fleet_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.kind.value,
                    job.interval_seconds,
                    job.state.value,
                    job.next_run_at,
                    json.dumps(dict(job.metadata), sort_keys=True, default=str),
                    job.created_at,
                    job.updated_at,
                ),
            )
            self._append_job_event_conn(conn, job.job_id, "created", principal, asdict(job))
            return job

    def update_job(
        self,
        kind: FleetJobKind,
        *,
        interval_seconds: int | None = None,
        state: FleetJobState | None = None,
        next_run_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        principal: str,
    ) -> ScheduledFleetJob:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_jobs WHERE kind = ?", (kind.value,)).fetchone()
            if row is None:
                raise KeyError(kind.value)
            current = self._job_from_row(row)
            updated = replace(
                current,
                interval_seconds=max(5, int(interval_seconds)) if interval_seconds is not None else current.interval_seconds,
                state=state or current.state,
                next_run_at=next_run_at if next_run_at is not None else current.next_run_at,
                metadata=dict(metadata) if metadata is not None else current.metadata,
                updated_at=utc_now_iso(),
            )
            updated.validate()
            conn.execute(
                "UPDATE fleet_jobs SET interval_seconds=?, state=?, next_run_at=?, metadata=?, updated_at=? WHERE job_id=?",
                (
                    updated.interval_seconds,
                    updated.state.value,
                    updated.next_run_at,
                    json.dumps(dict(updated.metadata), sort_keys=True, default=str),
                    updated.updated_at,
                    updated.job_id,
                ),
            )
            self._append_job_event_conn(conn, updated.job_id, "updated", principal, asdict(updated))
            return updated

    def mark_job_scheduled(self, job_id: str, *, next_run_at: str, principal: str) -> ScheduledFleetJob:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = self._job_from_row(row)
            now = utc_now_iso()
            conn.execute(
                "UPDATE fleet_jobs SET next_run_at=?, updated_at=? WHERE job_id=?",
                (next_run_at, now, job_id),
            )
            self._append_job_event_conn(conn, job_id, "scheduled", principal, {"next_run_at": next_run_at})
            return replace(current, next_run_at=next_run_at, updated_at=now)

    def get_job(self, kind: FleetJobKind) -> ScheduledFleetJob:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_jobs WHERE kind = ?", (kind.value,)).fetchone()
        if row is None:
            raise KeyError(kind.value)
        return self._job_from_row(row)

    def list_jobs(self) -> tuple[ScheduledFleetJob, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fleet_jobs ORDER BY kind").fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    def due_jobs(self, now_iso: str) -> tuple[ScheduledFleetJob, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_jobs WHERE state=? AND next_run_at<=? ORDER BY next_run_at, kind",
                (FleetJobState.ACTIVE.value, now_iso),
            ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> ScheduledFleetJob:
        return ScheduledFleetJob(
            job_id=row["job_id"],
            kind=FleetJobKind(row["kind"]),
            interval_seconds=int(row["interval_seconds"]),
            state=FleetJobState(row["state"]),
            next_run_at=row["next_run_at"],
            metadata=_loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _append_job_event_conn(
        self,
        conn: sqlite3.Connection,
        job_id: str,
        action: str,
        principal: str,
        payload: Mapping[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO fleet_job_events VALUES (?, ?, ?, ?, ?, ?)",
            (
                new_id("fleet-job-event"),
                job_id,
                action,
                principal,
                json.dumps(dict(payload), sort_keys=True, default=str),
                utc_now_iso(),
            ),
        )

    # ---- runs ---------------------------------------------------------
    def start_run(self, job: ScheduledFleetJob) -> FleetRunReceipt:
        receipt = FleetRunReceipt(
            job_id=job.job_id,
            kind=job.kind,
            status=FleetRunStatus.RUNNING,
            started_at=utc_now_iso(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fleet_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.run_id,
                    receipt.job_id,
                    receipt.kind.value,
                    receipt.status.value,
                    receipt.started_at,
                    None,
                    "",
                    "{}",
                ),
            )
        return receipt

    def finish_run(
        self,
        run_id: str,
        *,
        status: FleetRunStatus,
        summary: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> FleetRunReceipt:
        completed = utc_now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] != FleetRunStatus.RUNNING.value:
                return self._run_from_row(row)
            conn.execute(
                "UPDATE fleet_runs SET status=?, completed_at=?, summary=?, metadata=? WHERE run_id=?",
                (
                    status.value,
                    completed,
                    summary,
                    json.dumps(dict(metadata or {}), sort_keys=True, default=str),
                    run_id,
                ),
            )
            row = conn.execute("SELECT * FROM fleet_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_from_row(row)

    def list_runs(self, *, limit: int = 100) -> tuple[FleetRunReceipt, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> FleetRunReceipt:
        return FleetRunReceipt(
            run_id=row["run_id"],
            job_id=row["job_id"],
            kind=FleetJobKind(row["kind"]),
            status=FleetRunStatus(row["status"]),
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            summary=row["summary"],
            metadata=_loads(row["metadata"]),
        )

    # ---- incidents ----------------------------------------------------
    def open_incident(self, incident: RuntimeFleetIncident, *, principal: str = "aether.fleet") -> RuntimeFleetIncident:
        now = utc_now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_incidents WHERE fingerprint=?", (incident.fingerprint,)).fetchone()
            if row is None:
                normalized = replace(incident, first_seen_at=incident.first_seen_at or now, last_seen_at=now)
                conn.execute(
                    "INSERT INTO fleet_incidents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized.incident_id,
                        normalized.fingerprint,
                        normalized.kind.value,
                        normalized.severity.value,
                        normalized.driver_id,
                        normalized.summary,
                        json.dumps(dict(normalized.evidence), sort_keys=True, default=str),
                        normalized.first_seen_at,
                        normalized.last_seen_at,
                        normalized.occurrence_count,
                        normalized.cee_trigger_id,
                    ),
                )
                self._append_incident_transition_conn(
                    conn,
                    normalized.incident_id,
                    FleetIncidentState.OPEN,
                    principal,
                    "condition detected",
                    normalized.evidence,
                )
                return normalized
            current = self._incident_from_row(conn, row)
            count = int(row["occurrence_count"]) + 1
            conn.execute(
                "UPDATE fleet_incidents SET severity=?, summary=?, evidence=?, last_seen_at=?, occurrence_count=? WHERE incident_id=?",
                (
                    incident.severity.value,
                    incident.summary,
                    json.dumps(dict(incident.evidence), sort_keys=True, default=str),
                    now,
                    count,
                    row["incident_id"],
                ),
            )
            if current.state == FleetIncidentState.RESOLVED:
                self._append_incident_transition_conn(
                    conn,
                    row["incident_id"],
                    FleetIncidentState.OPEN,
                    principal,
                    "condition recurred",
                    incident.evidence,
                )
            row = conn.execute("SELECT * FROM fleet_incidents WHERE incident_id=?", (row["incident_id"],)).fetchone()
            return self._incident_from_row(conn, row)

    def transition_incident(
        self,
        incident_id: str,
        state: FleetIncidentState,
        *,
        principal: str,
        reason: str,
        payload: Mapping[str, Any] | None = None,
    ) -> RuntimeFleetIncident:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_incidents WHERE incident_id=?", (incident_id,)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            current = self._incident_from_row(conn, row)
            if current.state == state:
                return current
            self._append_incident_transition_conn(conn, incident_id, state, principal, reason, payload or {})
            return replace(current, state=state)

    def resolve_absent(self, active_fingerprints: Sequence[str], *, principal: str, reason: str, managed_by: str | None = None) -> tuple[RuntimeFleetIncident, ...]:
        active = set(active_fingerprints)
        resolved: list[RuntimeFleetIncident] = []
        for incident in self.list_incidents(states=(FleetIncidentState.OPEN, FleetIncidentState.ACKNOWLEDGED), limit=1000):
            if managed_by is not None and str(incident.evidence.get("managed_by") or "") != managed_by:
                continue
            if incident.fingerprint in active:
                continue
            resolved.append(self.transition_incident(
                incident.incident_id,
                FleetIncidentState.RESOLVED,
                principal=principal,
                reason=reason,
            ))
        return tuple(resolved)

    def mark_cee_trigger(self, incident_id: str, trigger_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE fleet_incidents SET cee_trigger_id=? WHERE incident_id=? AND cee_trigger_id IS NULL",
                (trigger_id, incident_id),
            )


    def incident_by_fingerprint(self, fingerprint: str) -> RuntimeFleetIncident | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
            return self._incident_from_row(conn, row) if row is not None else None

    def get_incident(self, incident_id: str) -> RuntimeFleetIncident:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM fleet_incidents WHERE incident_id=?", (incident_id,)).fetchone()
            if row is None:
                raise KeyError(incident_id)
            return self._incident_from_row(conn, row)

    def list_incidents(
        self,
        *,
        states: Sequence[FleetIncidentState] | None = None,
        limit: int = 200,
    ) -> tuple[RuntimeFleetIncident, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_incidents ORDER BY last_seen_at DESC, rowid DESC LIMIT ?",
                (max(1, min(int(limit), 2000)),),
            ).fetchall()
            values = tuple(self._incident_from_row(conn, row) for row in rows)
        if states is None:
            return values
        allowed = set(states)
        return tuple(item for item in values if item.state in allowed)

    def _incident_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> RuntimeFleetIncident:
        transition = conn.execute(
            "SELECT state FROM fleet_incident_transitions WHERE incident_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (row["incident_id"],),
        ).fetchone()
        state = FleetIncidentState(transition["state"]) if transition else FleetIncidentState.OPEN
        return RuntimeFleetIncident(
            incident_id=row["incident_id"],
            fingerprint=row["fingerprint"],
            kind=FleetIncidentKind(row["kind"]),
            severity=FleetIncidentSeverity(row["severity"]),
            driver_id=row["driver_id"],
            summary=row["summary"],
            evidence=_loads(row["evidence"]),
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            occurrence_count=int(row["occurrence_count"]),
            state=state,
            cee_trigger_id=row["cee_trigger_id"],
        )

    def _append_incident_transition_conn(
        self,
        conn: sqlite3.Connection,
        incident_id: str,
        state: FleetIncidentState,
        principal: str,
        reason: str,
        payload: Mapping[str, Any],
    ) -> None:
        conn.execute(
            "INSERT INTO fleet_incident_transitions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id("fleet-incident-transition"),
                incident_id,
                state.value,
                principal,
                reason,
                json.dumps(dict(payload), sort_keys=True, default=str),
                utc_now_iso(),
            ),
        )

    # ---- cost evidence ------------------------------------------------
    def record_cost(
        self,
        *,
        driver_id: str,
        task_id: str | None,
        cost_usd: float | None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        source: str = "runtime-telemetry",
        payload: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> str:
        event_id = new_id("fleet-cost")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fleet_cost_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    driver_id,
                    task_id,
                    float(cost_usd) if cost_usd is not None else None,
                    int(input_tokens) if input_tokens is not None else None,
                    int(output_tokens) if output_tokens is not None else None,
                    source,
                    json.dumps(dict(payload or {}), sort_keys=True, default=str),
                    created_at or utc_now_iso(),
                ),
            )
        return event_id

    def cost_usage(self, *, start_at: str, end_at: str) -> Mapping[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fleet_cost_events WHERE created_at>=? AND created_at<? ORDER BY created_at",
                (start_at, end_at),
            ).fetchall()
        known = [float(row["cost_usd"]) for row in rows if row["cost_usd"] is not None]
        return {
            "known_cost_usd": round(sum(known), 8),
            "known_cost_events": len(known),
            "unknown_cost_events": sum(1 for row in rows if row["cost_usd"] is None),
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in rows),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in rows),
            "event_count": len(rows),
        }

    def status(self) -> Mapping[str, int]:
        with self._connect() as conn:
            jobs = conn.execute("SELECT COUNT(*) FROM fleet_jobs").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM fleet_runs").fetchone()[0]
            incidents = conn.execute("SELECT COUNT(*) FROM fleet_incidents").fetchone()[0]
            costs = conn.execute("SELECT COUNT(*) FROM fleet_cost_events").fetchone()[0]
        open_incidents = len(self.list_incidents(states=(FleetIncidentState.OPEN, FleetIncidentState.ACKNOWLEDGED), limit=2000))
        return {
            "jobs": int(jobs),
            "runs": int(runs),
            "incidents": int(incidents),
            "open_incidents": int(open_incidents),
            "cost_events": int(costs),
        }
