"""Contracts for reversible, mandate-bound business experiments and measured demand."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from aether.utils.ids import new_id


class ExperimentStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    VALIDATING = "validating"
    PREVIEW_READY = "preview-ready"
    WAITING_EXTERNAL_REVIEW = "waiting-external-review"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ExperimentStepKind(StrEnum):
    WRITE_ARTIFACT = "write-artifact"
    VERIFY_ARTIFACT = "verify-artifact"
    PRIVATE_PREVIEW = "private-preview"
    MEASURE_DEMAND = "measure-demand"
    EXTERNAL_ACTION = "external-action"


class ExperimentStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class DemandSignalKind(StrEnum):
    PAGE_VIEW = "page-view"
    CTA_CLICK = "cta-click"
    WAITLIST_SIGNUP = "waitlist-signup"
    INTERVIEW = "interview"
    MANUAL_OBSERVATION = "manual-observation"
    SYNTHETIC = "synthetic"


class DemandEvidenceState(StrEnum):
    SYNTHETIC = "synthetic"
    MEASURED = "measured"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ExternalActionReviewState(StrEnum):
    REQUIRED = "required"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ExperimentStep:
    name: str
    kind: ExperimentStepKind
    capability: str
    payload: Mapping[str, Any]
    estimated_cost_usd: float = 0.0
    reversible: bool = True
    external_actions: int = 0
    step_id: str = field(default_factory=lambda: new_id("experiment-step"))


@dataclass(frozen=True)
class ReversibleExperimentPlan:
    candidate_id: str
    mandate_id: str
    objective: str
    hypothesis: str
    success_metrics: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    steps: tuple[ExperimentStep, ...]
    maximum_cost_usd: float
    maximum_duration_seconds: int
    maximum_artifact_bytes: int = 2_000_000
    maximum_artifact_files: int = 50
    private_preview: bool = True
    planner_id: str = "aether.experiment-planner"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    plan_id: str = field(default_factory=lambda: new_id("experiment-plan"))
    created_at: str = ""
    plan_hash: str = ""


@dataclass(frozen=True)
class ExperimentStepReceipt:
    run_id: str
    step_id: str
    status: ExperimentStepStatus
    started_at: str
    completed_at: str
    cost_usd: float
    output: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    receipt_id: str = field(default_factory=lambda: new_id("experiment-step-receipt"))


@dataclass(frozen=True)
class ExperimentRunReceipt:
    plan_id: str
    candidate_id: str
    mandate_id: str
    status: ExperimentStatus
    workspace_path: str
    started_at: str
    completed_at: str
    cost_usd: float
    step_receipt_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    preview_id: str | None = None
    stop_reason: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: new_id("experiment-run"))
    run_hash: str = ""


@dataclass(frozen=True)
class ExperimentArtifactReceipt:
    run_id: str
    relative_path: str
    content_hash: str
    size_bytes: int
    media_type: str
    validation_status: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    artifact_id: str = field(default_factory=lambda: new_id("experiment-artifact"))


@dataclass(frozen=True)
class PreviewDeploymentReceipt:
    run_id: str
    artifact_ids: tuple[str, ...]
    preview_root: str
    token_hash: str
    private: bool
    created_at: str
    expires_at: str
    status: str = "active"
    preview_id: str = field(default_factory=lambda: new_id("private-preview"))


@dataclass(frozen=True)
class DemandSignal:
    run_id: str
    kind: DemandSignalKind
    state: DemandEvidenceState
    quantity: float
    unit: str
    measured_at: str
    source: str
    external_reference: str | None = None
    verifier: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: new_id("demand-signal"))
    signal_hash: str = ""


@dataclass(frozen=True)
class ExternalActionReview:
    run_id: str
    step_id: str
    action_summary: str
    consequence: str
    requested_by: str
    requested_at: str
    expires_at: str
    state: ExternalActionReviewState = ExternalActionReviewState.REQUIRED
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str | None = None
    review_id: str = field(default_factory=lambda: new_id("external-action-review"))


class ExperimentError(RuntimeError):
    pass


class ExperimentNotFound(ExperimentError):
    pass


class ExperimentBlocked(ExperimentError):
    def __init__(self, blockers: Sequence[str]):
        self.blockers = tuple(blockers)
        super().__init__("experiment blocked: " + "; ".join(self.blockers))


def _safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    return value


def canonical_experiment_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(_safe(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def experiment_step_payload(item: ExperimentStep) -> dict[str, Any]:
    return {
        "name": item.name, "kind": item.kind.value, "capability": item.capability,
        "payload": dict(item.payload), "estimated_cost_usd": item.estimated_cost_usd,
        "reversible": item.reversible, "external_actions": item.external_actions, "step_id": item.step_id,
    }


def experiment_plan_payload(item: ReversibleExperimentPlan) -> dict[str, Any]:
    return {
        "candidate_id": item.candidate_id, "mandate_id": item.mandate_id, "objective": item.objective,
        "hypothesis": item.hypothesis, "success_metrics": list(item.success_metrics),
        "stop_conditions": list(item.stop_conditions), "steps": [experiment_step_payload(s) for s in item.steps],
        "maximum_cost_usd": item.maximum_cost_usd, "maximum_duration_seconds": item.maximum_duration_seconds,
        "maximum_artifact_bytes": item.maximum_artifact_bytes, "maximum_artifact_files": item.maximum_artifact_files,
        "private_preview": item.private_preview,
        "planner_id": item.planner_id, "metadata": dict(item.metadata), "plan_id": item.plan_id,
        "created_at": item.created_at, "plan_hash": item.plan_hash,
    }


def experiment_plan_hash(item: ReversibleExperimentPlan) -> str:
    payload = experiment_plan_payload(item)
    payload.pop("plan_id", None)
    payload.pop("created_at", None)
    payload.pop("plan_hash", None)
    for step in payload.get("steps", []):
        step.pop("step_id", None)
    return canonical_experiment_hash(payload)


def experiment_plan_from_payload(data: Mapping[str, Any]) -> ReversibleExperimentPlan:
    return ReversibleExperimentPlan(
        candidate_id=str(data["candidate_id"]), mandate_id=str(data["mandate_id"]), objective=str(data["objective"]),
        hypothesis=str(data["hypothesis"]), success_metrics=tuple(data.get("success_metrics", ())),
        stop_conditions=tuple(data.get("stop_conditions", ())),
        steps=tuple(ExperimentStep(
            name=str(s["name"]), kind=ExperimentStepKind(str(s["kind"])), capability=str(s["capability"]),
            payload=dict(s.get("payload", {})), estimated_cost_usd=float(s.get("estimated_cost_usd", 0)),
            reversible=bool(s.get("reversible", True)), external_actions=int(s.get("external_actions", 0)),
            step_id=str(s["step_id"]),
        ) for s in data.get("steps", ())),
        maximum_cost_usd=float(data["maximum_cost_usd"]), maximum_duration_seconds=int(data["maximum_duration_seconds"]),
        maximum_artifact_bytes=int(data.get("maximum_artifact_bytes", 2_000_000)),
        maximum_artifact_files=int(data.get("maximum_artifact_files", 50)), private_preview=bool(data.get("private_preview", True)),
        planner_id=str(data.get("planner_id", "aether.experiment-planner")), metadata=dict(data.get("metadata", {})),
        plan_id=str(data["plan_id"]), created_at=str(data.get("created_at", "")), plan_hash=str(data.get("plan_hash", "")),
    )


def experiment_run_payload(item: ExperimentRunReceipt) -> dict[str, Any]:
    return {
        "plan_id": item.plan_id, "candidate_id": item.candidate_id, "mandate_id": item.mandate_id,
        "status": item.status.value, "workspace_path": item.workspace_path, "started_at": item.started_at,
        "completed_at": item.completed_at, "cost_usd": item.cost_usd,
        "step_receipt_ids": list(item.step_receipt_ids), "artifact_ids": list(item.artifact_ids),
        "preview_id": item.preview_id, "stop_reason": item.stop_reason, "metadata": dict(item.metadata),
        "run_id": item.run_id, "run_hash": item.run_hash,
    }


def experiment_run_hash(item: ExperimentRunReceipt) -> str:
    payload = experiment_run_payload(item)
    payload.pop("run_hash", None)
    return canonical_experiment_hash(payload)


def demand_signal_payload(item: DemandSignal) -> dict[str, Any]:
    return {
        "run_id": item.run_id, "kind": item.kind.value, "state": item.state.value,
        "quantity": item.quantity, "unit": item.unit, "measured_at": item.measured_at,
        "source": item.source, "external_reference": item.external_reference,
        "verifier": item.verifier, "metadata": dict(item.metadata), "signal_id": item.signal_id,
        "signal_hash": item.signal_hash,
    }


def demand_signal_hash(item: DemandSignal) -> str:
    payload = demand_signal_payload(item)
    payload.pop("signal_id", None)
    payload.pop("signal_hash", None)
    return canonical_experiment_hash(payload)
