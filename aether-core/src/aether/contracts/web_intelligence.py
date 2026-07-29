"""Provider-neutral contracts for live web intelligence, conformance, and freshness."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from aether.utils.ids import new_id


class LiveSourceState(StrEnum):
    CONFIGURED = "configured"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class SourceConformanceState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"
    STALE = "stale"
    MISSING = "missing"


class FreshnessState(StrEnum):
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    MISSING = "missing"


class SourceDiscoveryState(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class LiveSourceConfiguration:
    adapter_id: str
    source_id: str
    endpoint: str
    allowed_domains: tuple[str, ...]
    blocked_domains: tuple[str, ...] = field(default_factory=tuple)
    credential_handle: str | None = None
    maximum_pages: int = 10
    maximum_depth: int = 3
    maximum_bytes: int = 2_000_000
    timeout_seconds: int = 120
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    config_id: str = field(default_factory=lambda: new_id("source-config"))
    configured_by: str = ""
    configured_at: str = ""
    configuration_hash: str = ""


@dataclass(frozen=True)
class SourceConformanceCheck:
    name: str
    passed: bool
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceConformanceReceipt:
    adapter_id: str
    source_id: str
    configuration_hash: str
    manifest_hash: str
    adapter_version: str
    state: SourceConformanceState
    checks: tuple[SourceConformanceCheck, ...]
    issued_by: str
    issued_at: str
    expires_at: str
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    receipt_id: str = field(default_factory=lambda: new_id("source-conformance"))
    receipt_hash: str = ""


@dataclass(frozen=True)
class EvidenceFreshnessPolicy:
    fresh_for_seconds: int = 86_400
    aging_for_seconds: int = 259_200
    maximum_stale_fraction: float = 0.35
    refresh_batch_size: int = 25

    def validate(self) -> None:
        if self.fresh_for_seconds < 1:
            raise ValueError("fresh_for_seconds must be positive")
        if self.aging_for_seconds < self.fresh_for_seconds:
            raise ValueError("aging_for_seconds must be >= fresh_for_seconds")
        if not 0 <= self.maximum_stale_fraction <= 1:
            raise ValueError("maximum_stale_fraction must be between 0 and 1")
        if self.refresh_batch_size < 1:
            raise ValueError("refresh_batch_size must be positive")


@dataclass(frozen=True)
class EvidenceFreshnessRecord:
    snapshot_id: str
    source_id: str
    canonical_url: str
    retrieved_at: str
    evaluated_at: str
    age_seconds: int
    state: FreshnessState
    refresh_required: bool
    content_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: new_id("freshness"))


@dataclass(frozen=True)
class SourceDiscoveryCandidate:
    discovered_url: str
    canonical_domain: str
    discovered_from_snapshot_ids: tuple[str, ...]
    capabilities: tuple[str, ...]
    reason: str
    confidence: float
    risk: str
    state: SourceDiscoveryState = SourceDiscoveryState.PROPOSED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_id: str = field(default_factory=lambda: new_id("source-discovery"))
    proposed_at: str = ""
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    candidate_hash: str = ""


class WebIntelligenceError(RuntimeError):
    pass


class WebIntelligenceBlocked(WebIntelligenceError):
    def __init__(self, blockers: Sequence[str]):
        self.blockers = tuple(blockers)
        super().__init__("web intelligence blocked: " + "; ".join(self.blockers))


class WebIntelligenceNotFound(WebIntelligenceError):
    pass


def _safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(item) for item in value]
    return value


def canonical_web_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def live_source_configuration_payload(item: LiveSourceConfiguration) -> dict[str, Any]:
    return {
        "adapter_id": item.adapter_id, "source_id": item.source_id, "endpoint": item.endpoint,
        "allowed_domains": list(item.allowed_domains), "blocked_domains": list(item.blocked_domains),
        # Store only an opaque handle, never credential contents.
        "credential_handle": item.credential_handle,
        "maximum_pages": item.maximum_pages, "maximum_depth": item.maximum_depth,
        "maximum_bytes": item.maximum_bytes, "timeout_seconds": item.timeout_seconds,
        "enabled": item.enabled, "metadata": dict(item.metadata), "config_id": item.config_id,
        "configured_by": item.configured_by, "configured_at": item.configured_at,
        "configuration_hash": item.configuration_hash,
    }


def live_source_configuration_hash(item: LiveSourceConfiguration) -> str:
    payload = live_source_configuration_payload(item)
    payload.pop("config_id", None)
    payload.pop("configured_by", None)
    payload.pop("configured_at", None)
    payload.pop("configuration_hash", None)
    return canonical_web_hash(payload)


def live_source_configuration_from_payload(data: Mapping[str, Any]) -> LiveSourceConfiguration:
    return LiveSourceConfiguration(
        adapter_id=str(data["adapter_id"]), source_id=str(data["source_id"]), endpoint=str(data["endpoint"]),
        allowed_domains=tuple(data.get("allowed_domains", ())), blocked_domains=tuple(data.get("blocked_domains", ())),
        credential_handle=data.get("credential_handle"), maximum_pages=int(data.get("maximum_pages", 10)),
        maximum_depth=int(data.get("maximum_depth", 3)), maximum_bytes=int(data.get("maximum_bytes", 2_000_000)),
        timeout_seconds=int(data.get("timeout_seconds", 120)), enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata", {})), config_id=str(data["config_id"]),
        configured_by=str(data.get("configured_by", "")), configured_at=str(data.get("configured_at", "")),
        configuration_hash=str(data.get("configuration_hash", "")),
    )


def source_conformance_receipt_payload(item: SourceConformanceReceipt) -> dict[str, Any]:
    return {
        "adapter_id": item.adapter_id, "source_id": item.source_id,
        "configuration_hash": item.configuration_hash, "manifest_hash": item.manifest_hash,
        "adapter_version": item.adapter_version, "state": item.state.value,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail, "evidence": dict(c.evidence)} for c in item.checks],
        "issued_by": item.issued_by, "issued_at": item.issued_at, "expires_at": item.expires_at,
        "error": item.error, "metadata": dict(item.metadata), "receipt_id": item.receipt_id,
        "receipt_hash": item.receipt_hash,
    }


def source_conformance_receipt_hash(item: SourceConformanceReceipt) -> str:
    payload = source_conformance_receipt_payload(item)
    payload.pop("receipt_id", None)
    payload.pop("receipt_hash", None)
    return canonical_web_hash(payload)


def source_conformance_receipt_from_payload(data: Mapping[str, Any]) -> SourceConformanceReceipt:
    return SourceConformanceReceipt(
        adapter_id=str(data["adapter_id"]), source_id=str(data["source_id"]),
        configuration_hash=str(data["configuration_hash"]), manifest_hash=str(data["manifest_hash"]),
        adapter_version=str(data.get("adapter_version", "")), state=SourceConformanceState(str(data["state"])),
        checks=tuple(SourceConformanceCheck(str(c["name"]), bool(c["passed"]), str(c["detail"]), dict(c.get("evidence", {}))) for c in data.get("checks", ())),
        issued_by=str(data["issued_by"]), issued_at=str(data["issued_at"]), expires_at=str(data["expires_at"]),
        error=data.get("error"), metadata=dict(data.get("metadata", {})), receipt_id=str(data["receipt_id"]),
        receipt_hash=str(data.get("receipt_hash", "")),
    )


def freshness_record_payload(item: EvidenceFreshnessRecord) -> dict[str, Any]:
    return {
        "snapshot_id": item.snapshot_id, "source_id": item.source_id, "canonical_url": item.canonical_url,
        "retrieved_at": item.retrieved_at, "evaluated_at": item.evaluated_at, "age_seconds": item.age_seconds,
        "state": item.state.value, "refresh_required": item.refresh_required, "content_hash": item.content_hash,
        "metadata": dict(item.metadata), "record_id": item.record_id,
    }


def source_discovery_candidate_payload(item: SourceDiscoveryCandidate) -> dict[str, Any]:
    return {
        "discovered_url": item.discovered_url, "canonical_domain": item.canonical_domain,
        "discovered_from_snapshot_ids": list(item.discovered_from_snapshot_ids),
        "capabilities": list(item.capabilities), "reason": item.reason, "confidence": item.confidence,
        "risk": item.risk, "state": item.state.value, "metadata": dict(item.metadata),
        "candidate_id": item.candidate_id, "proposed_at": item.proposed_at,
        "decided_by": item.decided_by, "decided_at": item.decided_at,
        "decision_reason": item.decision_reason, "candidate_hash": item.candidate_hash,
    }


def source_discovery_candidate_hash(item: SourceDiscoveryCandidate) -> str:
    payload = source_discovery_candidate_payload(item)
    for key in ("candidate_id", "proposed_at", "decided_by", "decided_at", "decision_reason", "candidate_hash", "state"):
        payload.pop(key, None)
    return canonical_web_hash(payload)
