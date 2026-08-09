"""Versioned work-packet schema ``aether.work-packet.v1``.

A work packet is a bounded, hash-bound envelope used to hand a phase unit of
work between producers and governed executors. It carries its own schema
version, provenance, explicit status, and a deterministic integrity hash. It is
a source-present contract only: nothing here executes work or mutates state.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping

WORK_PACKET_SCHEMA = "aether.work-packet.v1"


class WorkPacketStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkPacketValidationError(ValueError):
    pass


def _normalized(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (tuple, list)):
        return [_normalized(item) for item in value]
    return value


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _normalized(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class WorkPacket:
    schema: str
    work_packet_id: str
    kind: str
    status: WorkPacketStatus
    created_at: str
    producer: str
    phase: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence_links: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, WorkPacketStatus):
            object.__setattr__(self, "status", WorkPacketStatus(self.status))
        if self.schema != WORK_PACKET_SCHEMA:
            raise WorkPacketValidationError(
                f"work packet schema must be {WORK_PACKET_SCHEMA}"
            )
        if not str(self.work_packet_id).strip():
            raise WorkPacketValidationError("work packet ID must not be empty")
        if not str(self.kind).strip():
            raise WorkPacketValidationError("work packet kind must not be empty")
        if not str(self.producer).strip():
            raise WorkPacketValidationError("work packet producer must not be empty")
        if not str(self.phase).strip():
            raise WorkPacketValidationError("work packet phase must not be empty")
        if not str(self.created_at).strip():
            raise WorkPacketValidationError("work packet created time must not be empty")
        expected = _hash_payload(self._unsigned_payload())
        if self.hash and self.hash != expected:
            raise WorkPacketValidationError("work packet integrity hash mismatch")
        object.__setattr__(self, "hash", expected)

    def _unsigned_payload(self) -> Mapping[str, Any]:
        return {
            "schema": self.schema,
            "work_packet_id": self.work_packet_id,
            "kind": self.kind,
            "status": self.status.value,
            "created_at": self.created_at,
            "producer": self.producer,
            "phase": self.phase,
            "scope": dict(self.scope),
            "payload": dict(self.payload),
            "evidence_links": list(self.evidence_links),
            "metadata": dict(self.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def transition(self, status: WorkPacketStatus | str) -> "WorkPacket":
        target = WorkPacketStatus(status)
        if target is self.status:
            return self
        return WorkPacket(**{**self._unsigned_payload(), "status": target})


def build_work_packet(
    *,
    work_packet_id: str,
    kind: str,
    phase: str,
    producer: str,
    created_at: str,
    status: WorkPacketStatus | str = WorkPacketStatus.DRAFT,
    scope: Mapping[str, Any] | None = None,
    payload: Mapping[str, Any] | None = None,
    evidence_links: tuple[str, ...] = (),
    metadata: Mapping[str, Any] | None = None,
) -> WorkPacket:
    """Build a validated ``aether.work-packet.v1`` with a deterministic hash."""
    return WorkPacket(
        schema=WORK_PACKET_SCHEMA,
        work_packet_id=work_packet_id,
        kind=kind,
        status=status,
        created_at=created_at,
        producer=producer,
        phase=phase,
        scope=dict(scope or {}),
        payload=dict(payload or {}),
        evidence_links=tuple(evidence_links),
        metadata=dict(metadata or {}),
    )


def work_packet_v1(
    *,
    work_packet_id: str,
    kind: str,
    phase: str,
    producer: str,
    created_at: str,
    **values: Any,
) -> dict[str, Any]:
    """Convenience helper returning a validated packet as a dict."""
    return build_work_packet(
        work_packet_id=work_packet_id,
        kind=kind,
        phase=phase,
        producer=producer,
        created_at=created_at,
        **values,
    ).to_dict()
