"""Provider-neutral contracts for governed external nutrition intake."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from aether.contracts.opportunities import SourceCapability
from aether.utils.ids import new_id


class NutritionActivationState(StrEnum):
    DISCOVERED = "discovered"
    SNAPSHOTTED = "snapshotted"
    CLASSIFIED = "classified"
    NORMALIZED = "normalized"
    SANDBOXED = "sandboxed"
    BENCHMARKED = "benchmarked"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class NutritionConformanceState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class ExternalNutritionCandidate:
    repository: str
    commit_sha: str
    artifact_path: str
    artifact_hash: str
    license: str
    publisher: str
    requested_source_capabilities: tuple[SourceCapability, ...]
    required_adapter_ids: tuple[str, ...]
    normalization_target: str
    deterministic_checks: tuple[str, ...]
    heldout_checks: tuple[str, ...]
    side_effects: tuple[str, ...] = field(default_factory=tuple)
    runtime_requirements: tuple[str, ...] = field(default_factory=tuple)
    credential_requirements: tuple[str, ...] = field(default_factory=tuple)
    network_destinations: tuple[str, ...] = field(default_factory=tuple)
    install_behavior: tuple[str, ...] = field(default_factory=tuple)
    update_behavior: tuple[str, ...] = field(default_factory=tuple)
    activation_state: NutritionActivationState = NutritionActivationState.DISCOVERED
    metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_id: str = field(default_factory=lambda: new_id("nutrition-candidate"))


@dataclass(frozen=True)
class NutritionConformanceCheck:
    name: str
    passed: bool
    detail: str
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NutritionConformanceReceipt:
    candidate_id: str
    candidate_hash: str
    state: NutritionConformanceState
    checks: tuple[NutritionConformanceCheck, ...]
    eligible_for_benchmark: bool
    eligible_for_activation: bool
    required_adapter_manifest_hashes: Mapping[str, str]
    source_conformance_receipt_ids: tuple[str, ...]
    issued_by: str
    issued_at: str
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    receipt_id: str = field(default_factory=lambda: new_id("nutrition-conformance"))
    receipt_hash: str = ""


def _safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_safe(item) for item in value]
    return value


def canonical_nutrition_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def external_nutrition_candidate_payload(item: ExternalNutritionCandidate) -> dict[str, Any]:
    return {
        "repository": item.repository,
        "commit_sha": item.commit_sha,
        "artifact_path": item.artifact_path,
        "artifact_hash": item.artifact_hash,
        "license": item.license,
        "publisher": item.publisher,
        "requested_source_capabilities": [value.value for value in item.requested_source_capabilities],
        "required_adapter_ids": list(item.required_adapter_ids),
        "normalization_target": item.normalization_target,
        "deterministic_checks": list(item.deterministic_checks),
        "heldout_checks": list(item.heldout_checks),
        "side_effects": list(item.side_effects),
        "runtime_requirements": list(item.runtime_requirements),
        "credential_requirements": list(item.credential_requirements),
        "network_destinations": list(item.network_destinations),
        "install_behavior": list(item.install_behavior),
        "update_behavior": list(item.update_behavior),
        "activation_state": item.activation_state.value,
        "metadata": dict(item.metadata),
        "candidate_id": item.candidate_id,
    }


def external_nutrition_candidate_hash(item: ExternalNutritionCandidate) -> str:
    payload = external_nutrition_candidate_payload(item)
    payload.pop("candidate_id", None)
    return canonical_nutrition_hash(payload)


def nutrition_conformance_receipt_payload(item: NutritionConformanceReceipt) -> dict[str, Any]:
    return {
        "candidate_id": item.candidate_id,
        "candidate_hash": item.candidate_hash,
        "state": item.state.value,
        "checks": [
            {
                "name": check.name,
                "passed": check.passed,
                "detail": check.detail,
                "evidence": dict(check.evidence),
            }
            for check in item.checks
        ],
        "eligible_for_benchmark": item.eligible_for_benchmark,
        "eligible_for_activation": item.eligible_for_activation,
        "required_adapter_manifest_hashes": dict(item.required_adapter_manifest_hashes),
        "source_conformance_receipt_ids": list(item.source_conformance_receipt_ids),
        "issued_by": item.issued_by,
        "issued_at": item.issued_at,
        "error": item.error,
        "metadata": dict(item.metadata),
        "receipt_id": item.receipt_id,
        "receipt_hash": item.receipt_hash,
    }


def nutrition_conformance_receipt_hash(item: NutritionConformanceReceipt) -> str:
    payload = nutrition_conformance_receipt_payload(item)
    payload.pop("receipt_id", None)
    payload.pop("receipt_hash", None)
    return canonical_nutrition_hash(payload)
