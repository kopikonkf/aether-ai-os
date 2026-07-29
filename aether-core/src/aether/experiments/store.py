"""Append-only SQLite ledger for experiment plans, runs, artifacts, previews, demand, and reviews."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from aether.contracts.experiments import (
    DemandEvidenceState, DemandSignal, DemandSignalKind, ExperimentArtifactReceipt,
    ExperimentNotFound, ExperimentRunReceipt, ExperimentStatus, ExperimentStepReceipt,
    ExperimentStepStatus, ExternalActionReview, ExternalActionReviewState,
    PreviewDeploymentReceipt, ReversibleExperimentPlan, demand_signal_payload,
    experiment_plan_from_payload, experiment_plan_payload, experiment_run_payload,
)


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: str) -> Any:
    return json.loads(value)


class SQLiteExperimentStore:
    store_id = "reversible-experiments.sqlite.v1"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS experiment_plans(
                plan_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, mandate_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_step_receipts(
                receipt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_runs(
                run_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, run_hash TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS experiment_artifacts(
                artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, relative_path TEXT NOT NULL,
                content_hash TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(run_id, relative_path, content_hash)
            );
            CREATE TABLE IF NOT EXISTS preview_deployments(
                preview_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, token_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS demand_signals(
                signal_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, signal_hash TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL, payload_json TEXT NOT NULL, measured_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS external_action_reviews(
                review_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_id TEXT NOT NULL,
                state TEXT NOT NULL, payload_json TEXT NOT NULL, requested_at TEXT NOT NULL
            );
            """)
            for table in (
                "experiment_plans", "experiment_step_receipts", "experiment_runs",
                "experiment_artifacts", "preview_deployments", "demand_signals", "external_action_reviews",
            ):
                conn.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable append-only ledger'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'immutable append-only ledger'); END;
                """)

    def add_plan(self, item: ReversibleExperimentPlan) -> ReversibleExperimentPlan:
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO experiment_plans VALUES (?, ?, ?, ?, ?, ?)", (
                    item.plan_id, item.candidate_id, item.mandate_id, item.plan_hash,
                    _dump(experiment_plan_payload(item)), item.created_at,
                ))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM experiment_plans WHERE plan_hash=?", (item.plan_hash,)).fetchone()
                if row:
                    return experiment_plan_from_payload(_load(row["payload_json"]))
                raise
        return item

    def get_plan(self, plan_id: str) -> ReversibleExperimentPlan:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM experiment_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            raise ExperimentNotFound(plan_id)
        return experiment_plan_from_payload(_load(row["payload_json"]))

    def plans(self, limit: int = 100) -> list[ReversibleExperimentPlan]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM experiment_plans ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [experiment_plan_from_payload(_load(row["payload_json"])) for row in rows]

    def add_step_receipt(self, item: ExperimentStepReceipt) -> ExperimentStepReceipt:
        payload = {
            "run_id": item.run_id, "step_id": item.step_id, "status": item.status.value,
            "started_at": item.started_at, "completed_at": item.completed_at, "cost_usd": item.cost_usd,
            "output": dict(item.output), "error": item.error, "receipt_id": item.receipt_id,
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO experiment_step_receipts VALUES (?, ?, ?, ?, ?, ?)", (
                item.receipt_id, item.run_id, item.step_id, item.status.value, _dump(payload), item.completed_at,
            ))
        return item

    def step_receipts(self, run_id: str) -> list[ExperimentStepReceipt]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM experiment_step_receipts WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        out = []
        for row in rows:
            data = _load(row["payload_json"])
            out.append(ExperimentStepReceipt(
                run_id=data["run_id"], step_id=data["step_id"], status=ExperimentStepStatus(data["status"]),
                started_at=data["started_at"], completed_at=data["completed_at"], cost_usd=float(data["cost_usd"]),
                output=dict(data.get("output", {})), error=data.get("error"), receipt_id=data["receipt_id"],
            ))
        return out

    def add_run(self, item: ExperimentRunReceipt) -> ExperimentRunReceipt:
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO experiment_runs VALUES (?, ?, ?, ?, ?, ?)", (
                    item.run_id, item.plan_id, item.run_hash, item.status.value,
                    _dump(experiment_run_payload(item)), item.completed_at,
                ))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM experiment_runs WHERE run_hash=?", (item.run_hash,)).fetchone()
                if row:
                    return self._run_from_data(_load(row["payload_json"]))
                raise
        return item

    @staticmethod
    def _run_from_data(data: dict[str, Any]) -> ExperimentRunReceipt:
        return ExperimentRunReceipt(
            plan_id=data["plan_id"], candidate_id=data["candidate_id"], mandate_id=data["mandate_id"],
            status=ExperimentStatus(data["status"]), workspace_path=data["workspace_path"],
            started_at=data["started_at"], completed_at=data["completed_at"], cost_usd=float(data["cost_usd"]),
            step_receipt_ids=tuple(data.get("step_receipt_ids", ())), artifact_ids=tuple(data.get("artifact_ids", ())),
            preview_id=data.get("preview_id"), stop_reason=data.get("stop_reason"), metadata=dict(data.get("metadata", {})),
            run_id=data["run_id"], run_hash=data.get("run_hash", ""),
        )

    def get_run(self, run_id: str) -> ExperimentRunReceipt:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM experiment_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ExperimentNotFound(run_id)
        return self._run_from_data(_load(row["payload_json"]))

    def runs(self, limit: int = 100) -> list[ExperimentRunReceipt]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM experiment_runs ORDER BY completed_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._run_from_data(_load(row["payload_json"])) for row in rows]

    def add_artifact(self, item: ExperimentArtifactReceipt) -> ExperimentArtifactReceipt:
        payload = {
            "run_id": item.run_id, "relative_path": item.relative_path, "content_hash": item.content_hash,
            "size_bytes": item.size_bytes, "media_type": item.media_type,
            "validation_status": item.validation_status, "created_at": item.created_at,
            "metadata": dict(item.metadata), "artifact_id": item.artifact_id,
        }
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO experiment_artifacts VALUES (?, ?, ?, ?, ?, ?)", (
                    item.artifact_id, item.run_id, item.relative_path, item.content_hash, _dump(payload), item.created_at,
                ))
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT payload_json FROM experiment_artifacts WHERE run_id=? AND relative_path=? AND content_hash=?",
                    (item.run_id, item.relative_path, item.content_hash),
                ).fetchone()
                if row:
                    return self._artifact_from_data(_load(row["payload_json"]))
                raise
        return item

    @staticmethod
    def _artifact_from_data(data: dict[str, Any]) -> ExperimentArtifactReceipt:
        return ExperimentArtifactReceipt(
            run_id=data["run_id"], relative_path=data["relative_path"], content_hash=data["content_hash"],
            size_bytes=int(data["size_bytes"]), media_type=data["media_type"],
            validation_status=data["validation_status"], created_at=data["created_at"],
            metadata=dict(data.get("metadata", {})), artifact_id=data["artifact_id"],
        )

    def artifacts(self, run_id: str | None = None) -> list[ExperimentArtifactReceipt]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute("SELECT payload_json FROM experiment_artifacts WHERE run_id=? ORDER BY relative_path", (run_id,)).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM experiment_artifacts ORDER BY created_at DESC").fetchall()
        return [self._artifact_from_data(_load(row["payload_json"])) for row in rows]

    def add_preview(self, item: PreviewDeploymentReceipt) -> PreviewDeploymentReceipt:
        payload = {
            "run_id": item.run_id, "artifact_ids": list(item.artifact_ids), "preview_root": item.preview_root,
            "token_hash": item.token_hash, "private": item.private, "created_at": item.created_at,
            "expires_at": item.expires_at, "status": item.status, "preview_id": item.preview_id,
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO preview_deployments VALUES (?, ?, ?, ?, ?)", (
                item.preview_id, item.run_id, item.token_hash, _dump(payload), item.created_at,
            ))
        return item

    def get_preview(self, preview_id: str) -> PreviewDeploymentReceipt:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM preview_deployments WHERE preview_id=?", (preview_id,)).fetchone()
        if not row:
            raise ExperimentNotFound(preview_id)
        data = _load(row["payload_json"])
        return PreviewDeploymentReceipt(
            run_id=data["run_id"], artifact_ids=tuple(data.get("artifact_ids", ())), preview_root=data["preview_root"],
            token_hash=data["token_hash"], private=bool(data["private"]), created_at=data["created_at"],
            expires_at=data["expires_at"], status=data.get("status", "active"), preview_id=data["preview_id"],
        )

    def previews(self, limit: int = 100) -> list[PreviewDeploymentReceipt]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM preview_deployments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get_preview(_load(row["payload_json"])["preview_id"]) for row in rows]

    def add_signal(self, item: DemandSignal) -> DemandSignal:
        with self._connect() as conn:
            try:
                conn.execute("INSERT INTO demand_signals VALUES (?, ?, ?, ?, ?, ?)", (
                    item.signal_id, item.run_id, item.signal_hash, item.state.value,
                    _dump(demand_signal_payload(item)), item.measured_at,
                ))
            except sqlite3.IntegrityError:
                row = conn.execute("SELECT payload_json FROM demand_signals WHERE signal_hash=?", (item.signal_hash,)).fetchone()
                if row:
                    return self._signal_from_data(_load(row["payload_json"]))
                raise
        return item

    @staticmethod
    def _signal_from_data(data: dict[str, Any]) -> DemandSignal:
        return DemandSignal(
            run_id=data["run_id"], kind=DemandSignalKind(data["kind"]), state=DemandEvidenceState(data["state"]),
            quantity=float(data["quantity"]), unit=data["unit"], measured_at=data["measured_at"], source=data["source"],
            external_reference=data.get("external_reference"), verifier=data.get("verifier"),
            metadata=dict(data.get("metadata", {})), signal_id=data["signal_id"], signal_hash=data.get("signal_hash", ""),
        )

    def signals(self, run_id: str | None = None, limit: int = 500) -> list[DemandSignal]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute("SELECT payload_json FROM demand_signals WHERE run_id=? ORDER BY measured_at DESC LIMIT ?", (run_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM demand_signals ORDER BY measured_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._signal_from_data(_load(row["payload_json"])) for row in rows]

    def add_review(self, item: ExternalActionReview) -> ExternalActionReview:
        payload = {
            "run_id": item.run_id, "step_id": item.step_id, "action_summary": item.action_summary,
            "consequence": item.consequence, "requested_by": item.requested_by, "requested_at": item.requested_at,
            "expires_at": item.expires_at, "state": item.state.value, "decided_by": item.decided_by,
            "decided_at": item.decided_at, "reason": item.reason, "review_id": item.review_id,
        }
        with self._connect() as conn:
            conn.execute("INSERT INTO external_action_reviews VALUES (?, ?, ?, ?, ?, ?)", (
                item.review_id, item.run_id, item.step_id, item.state.value, _dump(payload), item.requested_at,
            ))
        return item

    def reviews(self, run_id: str | None = None, limit: int = 200) -> list[ExternalActionReview]:
        with self._connect() as conn:
            if run_id:
                rows = conn.execute("SELECT payload_json FROM external_action_reviews WHERE run_id=? ORDER BY requested_at DESC LIMIT ?", (run_id, limit)).fetchall()
            else:
                rows = conn.execute("SELECT payload_json FROM external_action_reviews ORDER BY requested_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            data = _load(row["payload_json"])
            out.append(ExternalActionReview(
                run_id=data["run_id"], step_id=data["step_id"], action_summary=data["action_summary"],
                consequence=data["consequence"], requested_by=data["requested_by"], requested_at=data["requested_at"],
                expires_at=data["expires_at"], state=ExternalActionReviewState(data["state"]),
                decided_by=data.get("decided_by"), decided_at=data.get("decided_at"), reason=data.get("reason"),
                review_id=data["review_id"],
            ))
        return out

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in (
                "experiment_plans", "experiment_step_receipts", "experiment_runs", "experiment_artifacts",
                "preview_deployments", "demand_signals", "external_action_reviews",
            )}
        return {"store_id": self.store_id, "path": str(self.path), **counts}
