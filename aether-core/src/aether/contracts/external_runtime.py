"""Provider-neutral streaming protocol contracts for external coding bodies."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


AETHER_CODING_STREAM_PROTOCOL = "aether.coding-jsonl.v1"


class RuntimeStreamFrameType(StrEnum):
    ACCEPTED = "task.accepted"
    PROGRESS = "task.progress"
    LOG = "task.log"
    PATCH = "artifact.patch"
    COMPLETED = "task.completed"
    ERROR = "task.error"


@dataclass(frozen=True)
class ExternalRuntimeHandshake:
    protocol: str
    runtime_id: str
    runtime_version: str
    display_name: str
    operations: tuple[str, ...]
    capabilities: tuple[str, ...]
    runtime_features: tuple[str, ...]
    max_frame_bytes: int
    max_patch_files: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = {
            "protocol": self.protocol,
            "runtime_id": self.runtime_id,
            "runtime_version": self.runtime_version,
            "operations": sorted(self.operations),
            "capabilities": sorted(self.capabilities),
            "runtime_features": sorted(self.runtime_features),
            "max_frame_bytes": self.max_frame_bytes,
            "max_patch_files": self.max_patch_files,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RuntimeStreamFrame:
    frame_type: RuntimeStreamFrameType
    task_id: str
    sequence: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    protocol: str = AETHER_CODING_STREAM_PROTOCOL


@dataclass(frozen=True)
class RuntimeGeneratedPatch:
    path: str
    content: str
    before_sha256: str | None
    kind: str = "upsert"
    runtime_diff: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
