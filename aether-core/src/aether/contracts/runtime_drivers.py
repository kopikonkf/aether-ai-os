"""Provider-neutral manifests, conformance receipts, and reliability contracts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable

from aether.utils.ids import new_id


class RuntimeDriverImplementation(StrEnum):
    LIVE = "live"
    DISCOVERY_ONLY = "discovery-only"
    PLANNED = "planned"


class RuntimeDriverAvailability(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class RuntimeConformanceState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"
    STALE = "stale"
    MISSING = "missing"


class RuntimeQuotaState(StrEnum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate-limited"
    QUOTA_EXHAUSTED = "quota-exhausted"
    AUTHENTICATION_FAILED = "authentication-failed"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeDriverManifest:
    driver_id: str
    display_name: str
    vendor: str
    implementation: RuntimeDriverImplementation
    protocol: str
    routing_key: str
    adapter_id: str
    executable_candidates: tuple[str, ...]
    version_argv: tuple[str, ...]
    operations: tuple[str, ...]
    capabilities: tuple[str, ...]
    runtime_features: tuple[str, ...]
    supported_platforms: tuple[str, ...]
    credential_env_names: tuple[str, ...] = field(default_factory=tuple)
    priority: int = 100
    enabled_by_default: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "driver_id": self.driver_id,
            "implementation": self.implementation.value,
            "protocol": self.protocol,
            "routing_key": self.routing_key,
            "adapter_id": self.adapter_id,
            "executable_candidates": list(self.executable_candidates),
            "version_argv": list(self.version_argv),
            "operations": sorted(self.operations),
            "capabilities": sorted(self.capabilities),
            "runtime_features": sorted(self.runtime_features),
            "supported_platforms": sorted(self.supported_platforms),
            "credential_env_names": sorted(self.credential_env_names),
            "priority": self.priority,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        if not self.driver_id.strip() or not self.routing_key.strip() or not self.adapter_id.strip():
            raise ValueError("driver_id, routing_key, and adapter_id are required")
        if not self.protocol.strip():
            raise ValueError("driver protocol is required")
        if self.implementation == RuntimeDriverImplementation.LIVE and not self.executable_candidates:
            raise ValueError("live driver requires at least one executable candidate")
        if self.implementation == RuntimeDriverImplementation.LIVE and not self.operations:
            raise ValueError("live driver requires at least one operation")
        if any(not item.strip() for item in self.credential_env_names):
            raise ValueError("credential environment names must be non-empty")


@dataclass(frozen=True)
class RuntimeDriverStatus:
    manifest: RuntimeDriverManifest
    availability: RuntimeDriverAvailability
    executable: str | None = None
    runtime_version: str | None = None
    auth_ready: bool = False
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConformanceCheck:
    name: str
    ok: bool
    detail: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConformanceReceipt:
    driver_id: str
    manifest_fingerprint: str
    executable_path: str
    executable_sha256: str
    runtime_version: str
    protocol: str
    provider_id: str
    model_id: str
    configuration_hash: str
    suite_hash: str
    issued_at: str
    expires_at: str
    checks: tuple[RuntimeConformanceCheck, ...]
    issued_by: str
    receipt_id: str = field(default_factory=lambda: new_id("runtime-conformance"))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(item.ok for item in self.checks)

    def fingerprint(self) -> str:
        payload = {
            "driver_id": self.driver_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "executable_path": self.executable_path,
            "executable_sha256": self.executable_sha256,
            "runtime_version": self.runtime_version,
            "protocol": self.protocol,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "configuration_hash": self.configuration_hash,
            "suite_hash": self.suite_hash,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "checks": [
                {"name": item.name, "ok": item.ok, "detail": item.detail, "metadata": dict(item.metadata)}
                for item in self.checks
            ],
            "issued_by": self.issued_by,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeConformanceAttestation:
    """Detached signer evidence for a conformance receipt fingerprint.

    Single-node v0.16 does not require an attestation for routing. Distributed
    deployments can inject a signer adapter without changing receipt semantics.
    """

    receipt_id: str
    receipt_fingerprint: str
    signer_id: str
    algorithm: str
    key_id: str
    signature: str
    issued_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class RuntimeConformanceReceiptSigner(Protocol):
    signer_id: str
    algorithm: str

    def sign(self, receipt: RuntimeConformanceReceipt) -> RuntimeConformanceAttestation:
        ...

    def verify(
        self,
        receipt: RuntimeConformanceReceipt,
        attestation: RuntimeConformanceAttestation,
    ) -> bool:
        ...


@dataclass(frozen=True)
class RuntimeReliabilitySnapshot:
    driver_id: str
    total_invocations: int
    successful_invocations: int
    failed_invocations: int
    verification_passes: int
    average_duration_seconds: float
    consecutive_failures: int
    score: float
    effective_priority_penalty: int
    computed_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeOperationsDriverSnapshot:
    driver_id: str
    availability: RuntimeDriverAvailability
    conformance_state: RuntimeConformanceState
    routing_eligible: bool
    runtime_version: str | None
    model_id: str
    provider_id: str
    reliability: RuntimeReliabilitySnapshot
    quota_state: RuntimeQuotaState
    receipt_id: str | None = None
    receipt_expires_at: str | None = None
    renewal_due: bool = False
    reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
