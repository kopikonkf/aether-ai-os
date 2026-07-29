"""Durable runtime conformance receipts and reliability-gated adapters."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aether.contracts import (
    RuntimeCommand, RuntimeConformanceCheck, RuntimeConformanceReceipt, RuntimeConformanceState,
    RuntimeDriverManifest, RuntimeReliabilitySnapshot, RuntimeResult,
)
from aether.contracts.coding_runtime import RuntimeDescriptor, RuntimeHealthStatus
from aether.utils.time import utc_now_iso


class RuntimeConformanceError(RuntimeError):
    pass


class RuntimeConformanceStore:
    """Append-only conformance ledger. New receipts supersede by recency only."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runtime_conformance_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    driver_id TEXT NOT NULL,
                    manifest_fingerprint TEXT NOT NULL,
                    executable_path TEXT NOT NULL,
                    executable_sha256 TEXT NOT NULL,
                    runtime_version TEXT NOT NULL,
                    protocol TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    configuration_hash TEXT NOT NULL,
                    suite_hash TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    checks_json TEXT NOT NULL,
                    issued_by TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    receipt_fingerprint TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS runtime_conformance_driver_idx
                ON runtime_conformance_receipts(driver_id, issued_at DESC);
                CREATE TRIGGER IF NOT EXISTS runtime_conformance_no_update
                BEFORE UPDATE ON runtime_conformance_receipts BEGIN
                  SELECT RAISE(ABORT, 'runtime conformance receipts are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS runtime_conformance_no_delete
                BEFORE DELETE ON runtime_conformance_receipts BEGIN
                  SELECT RAISE(ABORT, 'runtime conformance receipts are append-only');
                END;
            """)

    def append(self, receipt: RuntimeConformanceReceipt) -> RuntimeConformanceReceipt:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runtime_conformance_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    receipt.receipt_id, receipt.driver_id, receipt.manifest_fingerprint,
                    receipt.executable_path, receipt.executable_sha256, receipt.runtime_version,
                    receipt.protocol, receipt.provider_id, receipt.model_id, receipt.configuration_hash,
                    receipt.suite_hash, receipt.issued_at, receipt.expires_at,
                    json.dumps([asdict(item) for item in receipt.checks], sort_keys=True, default=str),
                    receipt.issued_by, json.dumps(dict(receipt.metadata), sort_keys=True, default=str),
                    receipt.fingerprint(),
                ),
            )
        return receipt

    def latest(self, driver_id: str) -> RuntimeConformanceReceipt | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM runtime_conformance_receipts WHERE driver_id = ? ORDER BY issued_at DESC, rowid DESC LIMIT 1",
                (driver_id,),
            ).fetchone()
        return _receipt(row) if row else None

    def list(self, *, driver_id: str | None = None, limit: int = 200) -> tuple[RuntimeConformanceReceipt, ...]:
        query = "SELECT * FROM runtime_conformance_receipts"
        params: list[Any] = []
        if driver_id:
            query += " WHERE driver_id = ?"
            params.append(driver_id)
        query += " ORDER BY issued_at DESC, rowid DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return tuple(_receipt(row) for row in rows)

    def validate(
        self,
        manifest: RuntimeDriverManifest,
        *,
        executable_path: str | None,
        executable_sha256: str | None,
        runtime_version: str | None,
        configuration_hash: str,
        now: datetime | None = None,
    ) -> tuple[RuntimeConformanceState, RuntimeConformanceReceipt | None, str]:
        receipt = self.latest(manifest.driver_id)
        if receipt is None:
            return RuntimeConformanceState.MISSING, None, "no conformance receipt"
        if not receipt.passed:
            return RuntimeConformanceState.FAILED, receipt, "latest receipt contains failed checks"
        current = now or datetime.now(timezone.utc)
        if _parse_time(receipt.expires_at) <= current:
            return RuntimeConformanceState.EXPIRED, receipt, "conformance receipt expired"
        expected = {
            "manifest": (receipt.manifest_fingerprint, manifest.fingerprint()),
            "executable": (receipt.executable_path, executable_path or ""),
            "executable_sha256": (receipt.executable_sha256, executable_sha256 or ""),
            "runtime_version": (receipt.runtime_version, runtime_version or ""),
            "configuration_hash": (receipt.configuration_hash, configuration_hash),
            "protocol": (receipt.protocol, manifest.protocol),
        }
        mismatches = [name for name, values in expected.items() if values[0] != values[1]]
        if mismatches:
            return RuntimeConformanceState.STALE, receipt, "receipt binding changed: " + ", ".join(mismatches)
        return RuntimeConformanceState.PASSED, receipt, "valid conformance receipt"


class ConformanceGatedRuntimeAdapter:
    """Adapter wrapper that excludes unreceipted binaries from live routing."""

    def __init__(
        self,
        delegate,
        manifest: RuntimeDriverManifest,
        store: RuntimeConformanceStore,
        *,
        executable_path: str | None,
        executable_sha256: str | None,
        runtime_version: str | None,
        configuration_hash: str,
        reliability: RuntimeReliabilitySnapshot | None = None,
        quota_state: str = "unknown",
        quota_priority_penalty: int = 0,
        configuration_hash_getter=None,
    ) -> None:
        self.delegate = delegate
        self.manifest = manifest
        self.store = store
        self.executable_path = executable_path
        self.executable_sha256 = executable_sha256
        self.runtime_version = runtime_version
        self.configuration_hash = configuration_hash
        self.configuration_hash_getter = configuration_hash_getter
        self.reliability = reliability
        self.quota_state = quota_state
        self.quota_priority_penalty = max(0, int(quota_priority_penalty))

    @property
    def adapter_id(self) -> str:
        return self.delegate.adapter_id

    def _state(self):
        current_executable_hash = self.executable_sha256
        if self.executable_path and Path(self.executable_path).is_file():
            try:
                current_executable_hash = executable_sha256(self.executable_path)
            except Exception:
                current_executable_hash = None
        current_configuration_hash = self.configuration_hash_getter() if callable(self.configuration_hash_getter) else self.configuration_hash
        return self.store.validate(
            self.manifest,
            executable_path=self.executable_path,
            executable_sha256=current_executable_hash,
            runtime_version=self.runtime_version,
            configuration_hash=current_configuration_hash,
        )

    @property
    def descriptor(self) -> RuntimeDescriptor:
        base = self.delegate.descriptor
        state, receipt, reason = self._state()
        reliability_penalty = self.reliability.effective_priority_penalty if self.reliability else 0
        penalty = reliability_penalty + self.quota_priority_penalty
        return replace(
            base,
            health_status=RuntimeHealthStatus.HEALTHY if state == RuntimeConformanceState.PASSED else RuntimeHealthStatus.DEGRADED,
            priority=base.priority + penalty,
            metadata={
                **dict(base.metadata),
                "conformance_state": state.value,
                "conformance_reason": reason,
                "conformance_receipt_id": receipt.receipt_id if receipt else None,
                "conformance_receipt_fingerprint": receipt.fingerprint() if receipt else None,
                "reliability_score": self.reliability.score if self.reliability else None,
                "effective_priority_penalty": penalty,
                "reliability_priority_penalty": reliability_penalty,
                "quota_state": self.quota_state,
                "quota_priority_penalty": self.quota_priority_penalty,
            },
        )

    async def capabilities(self) -> set[str]:
        return await self.delegate.capabilities()

    async def discover_descriptor(self) -> RuntimeDescriptor:
        await self.delegate.discover_descriptor()
        return self.descriptor

    async def health(self) -> Mapping[str, Any]:
        underlying = dict(await self.delegate.health())
        state, receipt, reason = self._state()
        return {
            **underlying,
            "ok": bool(underlying.get("ok")) and state == RuntimeConformanceState.PASSED,
            "degraded": state != RuntimeConformanceState.PASSED or bool(underlying.get("degraded")),
            "conformance_state": state.value,
            "conformance_reason": reason,
            "conformance_receipt_id": receipt.receipt_id if receipt else None,
            "quota_state": self.quota_state,
            "quota_priority_penalty": self.quota_priority_penalty,
        }

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        state, receipt, reason = self._state()
        if state != RuntimeConformanceState.PASSED:
            return RuntimeResult(False, error=f"RuntimeConformanceRequired: {reason}", metadata={
                "error_type": "RuntimeConformanceRequired",
                "driver_id": self.manifest.driver_id,
                "conformance_state": state.value,
                "receipt_id": receipt.receipt_id if receipt else None,
            })
        result = await self.delegate.execute(command)
        return RuntimeResult(result.ok, output=result.output, error=result.error, metadata={
            **dict(result.metadata),
            "driver_id": self.manifest.driver_id,
            "conformance_receipt_id": receipt.receipt_id if receipt else None,
            "conformance_receipt_fingerprint": receipt.fingerprint() if receipt else None,
        })


def executable_sha256(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_configuration_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reliability_snapshot(telemetry_db: Path, driver_id: str, adapter_id: str) -> RuntimeReliabilitySnapshot:
    now = utc_now_iso()
    if not telemetry_db.exists():
        return RuntimeReliabilitySnapshot(driver_id, 0, 0, 0, 0, 0.0, 0, 0.5, 10, now)
    conn = sqlite3.connect(telemetry_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ok, duration_seconds, verification_count, created_at FROM runtime_invocations WHERE adapter_id = ? ORDER BY created_at ASC",
            (adapter_id,),
        ).fetchall()
    finally:
        conn.close()
    total = len(rows)
    success = sum(int(row["ok"]) for row in rows)
    failed = total - success
    verification = sum(1 for row in rows if int(row["ok"]) and int(row["verification_count"]) > 0)
    average = (sum(float(row["duration_seconds"]) for row in rows) / total) if total else 0.0
    consecutive = 0
    for row in reversed(rows):
        if int(row["ok"]):
            break
        consecutive += 1
    success_rate = success / total if total else 0.5
    verification_rate = verification / success if success else (0.5 if total == 0 else 0.0)
    score = max(0.0, min(1.0, round(0.7 * success_rate + 0.3 * verification_rate - 0.08 * consecutive, 4)))
    penalty = min(50, int(round((1.0 - score) * 20)) + consecutive * 5)
    return RuntimeReliabilitySnapshot(driver_id, total, success, failed, verification, round(average, 6), consecutive, score, penalty, now)


def _receipt(row: sqlite3.Row) -> RuntimeConformanceReceipt:
    checks = tuple(RuntimeConformanceCheck(**item) for item in json.loads(row["checks_json"]))
    return RuntimeConformanceReceipt(
        driver_id=row["driver_id"], manifest_fingerprint=row["manifest_fingerprint"],
        executable_path=row["executable_path"], executable_sha256=row["executable_sha256"],
        runtime_version=row["runtime_version"], protocol=row["protocol"], provider_id=row["provider_id"],
        model_id=row["model_id"], configuration_hash=row["configuration_hash"], suite_hash=row["suite_hash"],
        issued_at=row["issued_at"], expires_at=row["expires_at"], checks=checks, issued_by=row["issued_by"],
        receipt_id=row["receipt_id"], metadata=json.loads(row["metadata_json"]),
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
