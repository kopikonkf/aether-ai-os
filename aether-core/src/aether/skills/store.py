"""Append-only SQLite store for skill candidates, registry, telemetry, and lifecycle."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from aether.contracts.evolution import EvolutionCheckKind, EvolutionCheckResult, EvolutionCommand
from aether.contracts.skills import (
    SkillBenchmark, SkillCandidate, SkillCandidateStatus, SkillDecision, SkillDecisionType,
    SkillInstallReceipt, SkillLifecycleAction, SkillLifecycleEvent, SkillLifecycleStatus,
    SkillManifest, SkillProvenance, SkillRecord, SkillTriggerType, SkillUsageContract, SkillUsageEvent,
    skill_manifest_hash,
)
from aether.utils.time import utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class SkillNotFound(KeyError):
    pass


class SkillDecisionConflict(RuntimeError):
    pass


class SkillIntegrityError(RuntimeError):
    pass


class SQLiteSkillStore:
    store_id = "aether.skills.sqlite"

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    deterministic_json TEXT NOT NULL,
                    heldout_json TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    retry_reason TEXT,
                    semantic_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_candidate_name ON skill_candidates(name, created_at DESC);

                CREATE TABLE IF NOT EXISTS skill_benchmarks (
                    benchmark_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES skill_candidates(candidate_id),
                    sandbox_id TEXT NOT NULL,
                    baseline_score REAL NOT NULL,
                    candidate_score REAL NOT NULL,
                    improvement REAL NOT NULL,
                    regression_count INTEGER NOT NULL,
                    checks_json TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    blockers_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_decisions (
                    decision_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES skill_candidates(candidate_id),
                    decision TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    skill_id TEXT,
                    decided_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_registry (
                    skill_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE REFERENCES skill_candidates(candidate_id),
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    install_receipt_json TEXT NOT NULL,
                    activated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_registry_name ON skill_registry(name, activated_at DESC);

                CREATE TABLE IF NOT EXISTS skill_usage (
                    usage_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL REFERENCES skill_registry(skill_id),
                    runtime_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    session_id TEXT,
                    event_id TEXT,
                    error_fingerprint TEXT,
                    metadata_json TEXT NOT NULL,
                    used_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_usage_skill ON skill_usage(skill_id, used_at DESC);

                CREATE TABLE IF NOT EXISTS skill_lifecycle (
                    lifecycle_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL REFERENCES skill_registry(skill_id),
                    action TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_skill_lifecycle_skill ON skill_lifecycle(skill_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS skill_learnings (
                    learning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id TEXT,
                    candidate_id TEXT,
                    fingerprint TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS skill_candidates_no_update BEFORE UPDATE ON skill_candidates
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_candidates_no_delete BEFORE DELETE ON skill_candidates
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_benchmarks_no_update BEFORE UPDATE ON skill_benchmarks
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_benchmarks_no_delete BEFORE DELETE ON skill_benchmarks
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_decisions_no_update BEFORE UPDATE ON skill_decisions
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_decisions_no_delete BEFORE DELETE ON skill_decisions
                BEGIN SELECT RAISE(ABORT, 'skill ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_registry_no_update BEFORE UPDATE ON skill_registry
                BEGIN SELECT RAISE(ABORT, 'skill registry is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS skill_registry_no_delete BEFORE DELETE ON skill_registry
                BEGIN SELECT RAISE(ABORT, 'skill registry is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS skill_usage_no_update BEFORE UPDATE ON skill_usage
                BEGIN SELECT RAISE(ABORT, 'skill telemetry is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_usage_no_delete BEFORE DELETE ON skill_usage
                BEGIN SELECT RAISE(ABORT, 'skill telemetry is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_lifecycle_no_update BEFORE UPDATE ON skill_lifecycle
                BEGIN SELECT RAISE(ABORT, 'skill lifecycle is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS skill_lifecycle_no_delete BEFORE DELETE ON skill_lifecycle
                BEGIN SELECT RAISE(ABORT, 'skill lifecycle is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS skill_learnings_no_update BEFORE UPDATE ON skill_learnings
                BEGIN SELECT RAISE(ABORT, 'skill learning ledger is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS skill_learnings_no_delete BEFORE DELETE ON skill_learnings
                BEGIN SELECT RAISE(ABORT, 'skill learning ledger is immutable'); END;
                """
            )

    def add_candidate(self, candidate: SkillCandidate, semantic_hash: str) -> SkillCandidate:
        normalized = replace(candidate, created_at=candidate.created_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.candidate_id, normalized.manifest.name, normalized.manifest.version,
                    _json(_manifest_dict(normalized.manifest)), normalized.artifact_hash,
                    _json(_provenance_dict(normalized.provenance)), _json(_commands_dict(normalized.deterministic_checks)),
                    _json(_commands_dict(normalized.heldout_checks)), normalized.rationale, normalized.retry_reason,
                    semantic_hash, normalized.created_at,
                ),
            )
        return normalized

    def get_candidate(self, candidate_id: str) -> SkillCandidate:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise SkillNotFound(candidate_id)
        return self._decorate_candidate(self._row_candidate(row))

    def list_candidates(self, limit: int = 100) -> tuple[SkillCandidate, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM skill_candidates ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return tuple(self._decorate_candidate(self._row_candidate(row)) for row in rows)

    def candidates_for_name(self, name: str, limit: int = 100) -> tuple[SkillCandidate, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_candidates WHERE name=? ORDER BY created_at DESC LIMIT ?", (name, limit)
            ).fetchall()
        return tuple(self._decorate_candidate(self._row_candidate(row)) for row in rows)

    def add_benchmark(self, benchmark: SkillBenchmark) -> SkillBenchmark:
        normalized = replace(benchmark, created_at=benchmark.created_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_benchmarks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.benchmark_id, normalized.candidate_id, normalized.sandbox_id,
                    normalized.baseline_score, normalized.candidate_score, normalized.improvement,
                    normalized.regression_count, _json([_check_dict(item) for item in normalized.checks]),
                    int(normalized.passed), _json(normalized.blockers), _json(dict(normalized.metadata)),
                    normalized.created_at,
                ),
            )
        return normalized

    def get_benchmark(self, candidate_id: str) -> SkillBenchmark | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_benchmarks WHERE candidate_id=?", (candidate_id,)).fetchone()
        return self._row_benchmark(row) if row else None

    def add_decision(self, decision: SkillDecision) -> SkillDecision:
        normalized = replace(decision, decided_at=decision.decided_at or utc_now())
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO skill_decisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        normalized.decision_id, normalized.candidate_id, normalized.decision.value,
                        normalized.principal, normalized.channel, normalized.reason, normalized.skill_id,
                        normalized.decided_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            existing = self.get_decision(normalized.candidate_id)
            if existing and existing.decision == normalized.decision:
                return existing
            raise SkillDecisionConflict(f"candidate {normalized.candidate_id} already has a terminal decision") from exc
        return normalized

    def get_decision(self, candidate_id: str) -> SkillDecision | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_decisions WHERE candidate_id=?", (candidate_id,)).fetchone()
        if not row:
            return None
        return SkillDecision(
            decision_id=row["decision_id"], candidate_id=row["candidate_id"],
            decision=SkillDecisionType(row["decision"]), principal=row["principal"], channel=row["channel"],
            reason=row["reason"], skill_id=row["skill_id"], decided_at=row["decided_at"],
        )

    def add_record(self, record: SkillRecord) -> SkillRecord:
        normalized = replace(record, activated_at=record.activated_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_registry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.skill_id, normalized.candidate_id, normalized.manifest.name,
                    normalized.manifest.version, _json(_manifest_dict(normalized.manifest)),
                    _json(_provenance_dict(normalized.provenance)), normalized.artifact_hash,
                    normalized.principal, normalized.reason, _json(_receipt_dict(normalized.install_receipt)),
                    normalized.activated_at,
                ),
            )
        return normalized

    def get_record(self, skill_id: str) -> SkillRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skill_registry WHERE skill_id=?", (skill_id,)).fetchone()
        if row is None:
            raise SkillNotFound(skill_id)
        return self._decorate_record(self._row_record(row))

    def list_records(self, limit: int = 100) -> tuple[SkillRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM skill_registry ORDER BY activated_at DESC LIMIT ?", (limit,)).fetchall()
        return tuple(self._decorate_record(self._row_record(row)) for row in rows)

    def active_for_name(self, name: str) -> SkillRecord | None:
        for record in self.list_records(limit=1000):
            if record.manifest.name == name and record.lifecycle_status in {SkillLifecycleStatus.ACTIVE, SkillLifecycleStatus.STALE}:
                return record
        return None

    def add_usage(self, usage: SkillUsageEvent) -> SkillUsageEvent:
        normalized = replace(usage, used_at=usage.used_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.usage_id, normalized.skill_id, normalized.runtime_id, int(normalized.success),
                    normalized.duration_seconds, normalized.session_id, normalized.event_id,
                    normalized.error_fingerprint, _json(dict(normalized.metadata)), normalized.used_at,
                ),
            )
        return normalized

    def usages(self, skill_id: str, limit: int = 1000) -> tuple[SkillUsageEvent, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_usage WHERE skill_id=? ORDER BY used_at DESC LIMIT ?", (skill_id, limit)
            ).fetchall()
        return tuple(SkillUsageEvent(
            usage_id=row["usage_id"], skill_id=row["skill_id"], runtime_id=row["runtime_id"],
            success=bool(row["success"]), duration_seconds=float(row["duration_seconds"]),
            session_id=row["session_id"], event_id=row["event_id"], error_fingerprint=row["error_fingerprint"],
            metadata=json.loads(row["metadata_json"]), used_at=row["used_at"],
        ) for row in rows)

    def add_lifecycle(self, event: SkillLifecycleEvent) -> SkillLifecycleEvent:
        normalized = replace(event, created_at=event.created_at or utc_now())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_lifecycle VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    normalized.lifecycle_id, normalized.skill_id, normalized.action.value,
                    normalized.principal, normalized.channel, normalized.reason, normalized.created_at,
                ),
            )
        return normalized

    def lifecycle_events(self, skill_id: str) -> tuple[SkillLifecycleEvent, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_lifecycle WHERE skill_id=? ORDER BY created_at ASC", (skill_id,)
            ).fetchall()
        return tuple(SkillLifecycleEvent(
            lifecycle_id=row["lifecycle_id"], skill_id=row["skill_id"],
            action=SkillLifecycleAction(row["action"]), principal=row["principal"], channel=row["channel"],
            reason=row["reason"], created_at=row["created_at"],
        ) for row in rows)

    def add_learning(self, *, fingerprint: str, outcome: str, summary: str, skill_id: str | None = None,
                     candidate_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO skill_learnings(skill_id,candidate_id,fingerprint,outcome,summary,metadata_json,created_at) VALUES (?,?,?,?,?,?,?)",
                (skill_id, candidate_id, fingerprint, outcome, summary, _json(metadata or {}), utc_now()),
            )

    def learnings(self, fingerprint: str, limit: int = 20) -> tuple[dict[str, Any], ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM skill_learnings WHERE fingerprint=? ORDER BY created_at DESC LIMIT ?", (fingerprint, limit)
            ).fetchall()
        return tuple(dict(row) | {"metadata": json.loads(row["metadata_json"])} for row in rows)

    def _decorate_candidate(self, candidate: SkillCandidate) -> SkillCandidate:
        benchmark = self.get_benchmark(candidate.candidate_id)
        decision = self.get_decision(candidate.candidate_id)
        status = SkillCandidateStatus.DRAFT
        skill_id = None
        if benchmark and benchmark.passed:
            status = SkillCandidateStatus.VERIFIED
        if decision and decision.decision == SkillDecisionType.REJECT:
            status = SkillCandidateStatus.REJECTED
        if decision and decision.decision == SkillDecisionType.ACTIVATE:
            status = SkillCandidateStatus.ACTIVE
            skill_id = decision.skill_id
        return replace(
            candidate, status=status, benchmark_id=benchmark.benchmark_id if benchmark else None,
            decision_id=decision.decision_id if decision else None, skill_id=skill_id,
        )

    def _decorate_record(self, record: SkillRecord) -> SkillRecord:
        status = SkillLifecycleStatus.ACTIVE
        for event in self.lifecycle_events(record.skill_id):
            status = {
                SkillLifecycleAction.MARK_STALE: SkillLifecycleStatus.STALE,
                SkillLifecycleAction.ARCHIVE: SkillLifecycleStatus.ARCHIVED,
                SkillLifecycleAction.REACTIVATE: SkillLifecycleStatus.ACTIVE,
                SkillLifecycleAction.SUPERSEDE: SkillLifecycleStatus.SUPERSEDED,
            }[event.action]
        return replace(record, lifecycle_status=status)

    @staticmethod
    def _row_candidate(row: sqlite3.Row) -> SkillCandidate:
        manifest = _manifest(json.loads(row["manifest_json"]))
        if skill_manifest_hash(manifest) != row["artifact_hash"]:
            raise SkillIntegrityError(f"candidate artifact hash mismatch: {row['candidate_id']}")
        return SkillCandidate(
            candidate_id=row["candidate_id"], manifest=manifest,
            provenance=_provenance(json.loads(row["provenance_json"])),
            deterministic_checks=_commands(json.loads(row["deterministic_json"])),
            heldout_checks=_commands(json.loads(row["heldout_json"])), rationale=row["rationale"],
            retry_reason=row["retry_reason"], created_at=row["created_at"],
        )

    @staticmethod
    def _row_benchmark(row: sqlite3.Row) -> SkillBenchmark:
        checks = tuple(EvolutionCheckResult(
            name=item["name"], kind=EvolutionCheckKind(item["kind"]), phase=item["phase"],
            passed=bool(item["passed"]), exit_code=int(item["exit_code"]),
            duration_seconds=float(item["duration_seconds"]), stdout=item.get("stdout", ""), stderr=item.get("stderr", ""),
        ) for item in json.loads(row["checks_json"]))
        return SkillBenchmark(
            benchmark_id=row["benchmark_id"], candidate_id=row["candidate_id"], sandbox_id=row["sandbox_id"],
            baseline_score=float(row["baseline_score"]), candidate_score=float(row["candidate_score"]),
            improvement=float(row["improvement"]), regression_count=int(row["regression_count"]), checks=checks,
            passed=bool(row["passed"]), blockers=tuple(json.loads(row["blockers_json"])),
            metadata=json.loads(row["metadata_json"]), created_at=row["created_at"],
        )

    @staticmethod
    def _row_record(row: sqlite3.Row) -> SkillRecord:
        manifest = _manifest(json.loads(row["manifest_json"]))
        if skill_manifest_hash(manifest) != row["artifact_hash"]:
            raise SkillIntegrityError(f"registry artifact hash mismatch: {row['skill_id']}")
        return SkillRecord(
            skill_id=row["skill_id"], candidate_id=row["candidate_id"],
            manifest=manifest,
            provenance=_provenance(json.loads(row["provenance_json"])), artifact_hash=row["artifact_hash"],
            principal=row["principal"], reason=row["reason"],
            install_receipt=_receipt(json.loads(row["install_receipt_json"])), activated_at=row["activated_at"],
        )


def _manifest_dict(manifest: SkillManifest) -> dict[str, Any]:
    return {
        "name": manifest.name, "version": manifest.version, "summary": manifest.summary,
        "instructions": manifest.instructions, "tags": list(manifest.tags), "metadata": dict(manifest.metadata),
        "usage": {
            "capabilities": list(manifest.usage.capabilities), "input_schema": dict(manifest.usage.input_schema),
            "output_schema": dict(manifest.usage.output_schema), "side_effects": list(manifest.usage.side_effects),
            "runtime_requirements": list(manifest.usage.runtime_requirements),
        },
    }


def _manifest(data: dict[str, Any]) -> SkillManifest:
    usage = data["usage"]
    return SkillManifest(
        name=data["name"], version=data["version"], summary=data["summary"], instructions=data["instructions"],
        usage=SkillUsageContract(
            capabilities=tuple(usage["capabilities"]), input_schema=usage.get("input_schema", {}),
            output_schema=usage.get("output_schema", {}), side_effects=tuple(usage.get("side_effects", [])),
            runtime_requirements=tuple(usage.get("runtime_requirements", [])),
        ),
        tags=tuple(data.get("tags", [])), metadata=data.get("metadata", {}),
    )


def _provenance_dict(value: SkillProvenance) -> dict[str, Any]:
    return {
        "trigger_type": value.trigger_type.value, "trigger_fingerprint": value.trigger_fingerprint,
        "evidence_ids": list(value.evidence_ids), "observed_count": value.observed_count,
        "successful_count": value.successful_count, "source_workflow": value.source_workflow,
        "generator_id": value.generator_id, "prior_skill_id": value.prior_skill_id,
        "metadata": dict(value.metadata),
    }


def _provenance(data: dict[str, Any]) -> SkillProvenance:
    return SkillProvenance(
        trigger_type=SkillTriggerType(data["trigger_type"]), trigger_fingerprint=data["trigger_fingerprint"],
        evidence_ids=tuple(data.get("evidence_ids", [])), observed_count=int(data.get("observed_count", 0)),
        successful_count=int(data.get("successful_count", 0)), source_workflow=data.get("source_workflow"),
        generator_id=data.get("generator_id", "external"), prior_skill_id=data.get("prior_skill_id"),
        metadata=data.get("metadata", {}),
    )


def _commands_dict(commands: tuple[EvolutionCommand, ...]) -> list[dict[str, Any]]:
    return [{"argv": list(item.argv), "kind": item.kind.value, "name": item.name, "timeout_seconds": item.timeout_seconds} for item in commands]


def _commands(data: list[dict[str, Any]]) -> tuple[EvolutionCommand, ...]:
    return tuple(EvolutionCommand(argv=tuple(item["argv"]), kind=EvolutionCheckKind(item["kind"]), name=item["name"], timeout_seconds=int(item.get("timeout_seconds", 120))) for item in data)


def _check_dict(item: EvolutionCheckResult) -> dict[str, Any]:
    return {
        "name": item.name, "kind": item.kind.value, "phase": item.phase, "passed": item.passed,
        "exit_code": item.exit_code, "duration_seconds": item.duration_seconds,
        "stdout": item.stdout, "stderr": item.stderr,
    }


def _receipt_dict(value: SkillInstallReceipt) -> dict[str, Any]:
    return {
        "adapter_id": value.adapter_id, "install_path": value.install_path,
        "activation_pointer": value.activation_pointer, "previous_pointer_content": value.previous_pointer_content,
        "metadata": dict(value.metadata),
    }


def _receipt(data: dict[str, Any]) -> SkillInstallReceipt:
    return SkillInstallReceipt(
        adapter_id=data["adapter_id"], install_path=data["install_path"], activation_pointer=data["activation_pointer"],
        previous_pointer_content=data.get("previous_pointer_content"), metadata=data.get("metadata", {}),
    )
