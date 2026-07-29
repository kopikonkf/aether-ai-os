"""Runtime-neutral contracts for governed coding bodies.

Aether Core owns task intent, governance, and evidence. Concrete coding
runtimes implement these contracts outside Core and remain replaceable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from aether.utils.ids import new_id


class CodingExecutionStatus(StrEnum):
    SELECTED = "selected"
    PENDING_APPROVAL = "pending-approval"
    COMPLETED = "completed"
    FALLBACK_COMPLETED = "fallback-completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    ESCALATED = "operator-escalation"


class RuntimeHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class CodingArtifactKind(StrEnum):
    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class WorkspaceBinding:
    workspace_id: str
    root_path: str
    session_id: str
    allowed_relative_paths: tuple[str, ...] = (".",)
    writable: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    binding_id: str = field(default_factory=lambda: new_id("workspace-binding"))


@dataclass(frozen=True)
class CodingEdit:
    path: str
    content: str
    expected_sha256: str | None = None


@dataclass(frozen=True)
class VerificationCommand:
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0
    label: str = "verification"


@dataclass(frozen=True)
class CodingTask:
    objective: str
    workspace_id: str
    session_id: str
    edits: tuple[CodingEdit, ...] = field(default_factory=tuple)
    verification_commands: tuple[VerificationCommand, ...] = field(default_factory=tuple)
    required_capabilities: tuple[str, ...] = ("coding.edit",)
    required_runtime_features: tuple[str, ...] = field(default_factory=tuple)
    max_artifacts: int = 10
    max_total_bytes: int = 262144
    allow_fallback: bool = True
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: new_id("coding-task"))


@dataclass(frozen=True)
class RuntimeDescriptor:
    routing_key: str
    adapter_id: str
    display_name: str
    operations: tuple[str, ...]
    capabilities: tuple[str, ...]
    runtime_features: tuple[str, ...]
    health_status: RuntimeHealthStatus
    priority: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeProgress:
    task_id: str
    phase: str
    message: str
    sequence: int
    percent: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    progress_id: str = field(default_factory=lambda: new_id("runtime-progress"))


@dataclass(frozen=True)
class CodingArtifact:
    path: str
    kind: CodingArtifactKind
    before_sha256: str | None
    after_sha256: str | None
    size_bytes: int
    diff: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    artifact_id: str = field(default_factory=lambda: new_id("coding-artifact"))


@dataclass(frozen=True)
class VerificationReceipt:
    label: str
    argv: tuple[str, ...]
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    metadata: Mapping[str, Any] = field(default_factory=dict)
    receipt_id: str = field(default_factory=lambda: new_id("verification"))


@dataclass(frozen=True)
class CodingTaskResult:
    task_id: str
    runtime_adapter_id: str
    ok: bool
    status: CodingExecutionStatus
    artifacts: tuple[CodingArtifact, ...] = field(default_factory=tuple)
    verification: tuple[VerificationReceipt, ...] = field(default_factory=tuple)
    progress: tuple[RuntimeProgress, ...] = field(default_factory=tuple)
    error: str | None = None
    rollback_performed: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)
    failure_fingerprint: str | None = None


@dataclass(frozen=True)
class CodingExecution:
    task: CodingTask
    status: CodingExecutionStatus
    ok: bool
    selected_runtime_id: str | None = None
    result: CodingTaskResult | None = None
    attempts: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    blockers: tuple[str, ...] = field(default_factory=tuple)
    failure_fingerprint: str | None = None
    action_result: Any = None


def coding_task_fingerprint(task: CodingTask, *, error: str = "") -> str:
    payload = {
        "objective": task.objective.strip(),
        "workspace_id": task.workspace_id,
        "session_id": task.session_id,
        "edits": [
            {"path": item.path, "content_sha256": hashlib.sha256(item.content.encode("utf-8")).hexdigest(), "expected_sha256": item.expected_sha256}
            for item in task.edits
        ],
        "verification": [{"argv": list(item.argv), "label": item.label} for item in task.verification_commands],
        "required_capabilities": sorted(task.required_capabilities),
        "required_runtime_features": sorted(task.required_runtime_features),
        "error": error.strip(),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@runtime_checkable
class RuntimeDirectory(Protocol):
    async def discover(self) -> Sequence[RuntimeDescriptor]: ...


@runtime_checkable
class WorkspaceBindingResolver(Protocol):
    def resolve(self, workspace_id: str, session_id: str) -> WorkspaceBinding: ...
