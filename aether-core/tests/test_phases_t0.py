from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aether.contracts.event_types import EventType
from aether.contracts.memory import MemoryKind
from aether.events import EventBus
from aether.memory import (
    AetherMemoryFabric,
    SQLiteCanonicalMemoryStore,
    SQLiteLexicalMemoryProvider,
)
from aether.phases import (
    PhaseObserver,
    WorkPacket,
    WorkPacketStatus,
    WorkPacketValidationError,
    build_work_packet,
    work_packet_v1,
)


def _fabric(tmp_path: Path) -> AetherMemoryFabric:
    canonical = SQLiteCanonicalMemoryStore(tmp_path / "canonical.sqlite3")
    return AetherMemoryFabric(
        canonical,
        SQLiteLexicalMemoryProvider(tmp_path / "retrieval.sqlite3", canonical),
    )


def test_work_packet_v1_is_versioned_and_hash_bound() -> None:
    packet = build_work_packet(
        work_packet_id="wp.1",
        kind="phase-observe",
        phase="t0",
        producer="aether.phases",
        created_at="2026-08-09T00:00:00Z",
        payload={"event_type": "mission.completed"},
    )

    assert packet.schema == "aether.work-packet.v1"
    assert packet.status is WorkPacketStatus.DRAFT
    assert len(packet.hash) == 64
    assert packet.to_dict()["hash"] == packet.hash


def test_work_packet_integrity_mismatch_is_rejected() -> None:
    with pytest.raises(WorkPacketValidationError, match="integrity"):
        WorkPacket(
            schema="aether.work-packet.v1",
            work_packet_id="wp.tampered",
            kind="phase-observe",
            status=WorkPacketStatus.DRAFT,
            created_at="2026-08-09T00:00:00Z",
            producer="aether.phases",
            phase="t0",
            hash="a" * 64,
        )


def test_work_packet_rejects_foreign_schema_and_empty_fields() -> None:
    with pytest.raises(WorkPacketValidationError, match="schema"):
        WorkPacket(
            schema="aether.work-packet.v0",
            work_packet_id="wp.foreign",
            kind="x",
            status=WorkPacketStatus.DRAFT,
            created_at="2026-08-09T00:00:00Z",
            producer="aether.phases",
            phase="t0",
        )
    with pytest.raises(WorkPacketValidationError, match="must not be empty"):
        WorkPacket(
            schema="aether.work-packet.v1",
            work_packet_id="",
            kind="x",
            status=WorkPacketStatus.DRAFT,
            created_at="2026-08-09T00:00:00Z",
            producer="aether.phases",
            phase="t0",
        )


def test_work_packet_transition_is_functional_and_rebounds_hash() -> None:
    packet = build_work_packet(
        work_packet_id="wp.3",
        kind="phase-observe",
        phase="t0",
        producer="aether.phases",
        created_at="2026-08-09T00:00:00Z",
    )
    ready = packet.transition(WorkPacketStatus.READY)
    assert ready.status is WorkPacketStatus.READY
    # Status is part of the bound payload: the transition must rebind integrity.
    assert len(ready.hash) == 64
    assert ready.hash != packet.hash
    assert WorkPacket(**ready.to_dict()).hash == ready.hash


def test_phase_observer_records_proposal_only_candidate(tmp_path: Path) -> None:
    event_bus = EventBus(tmp_path / "events.jsonl")
    fabric = _fabric(tmp_path)
    observer = PhaseObserver(
        event_bus,
        fabric,
        source="test-observer",
        emit_events=True,
    )

    event_bus.emit(
        EventType.MISSION_COMPLETED,
        actor="aether.missions",
        payload={"mission_id": "m.1"},
    )

    records = asyncio.run(fabric.canonical.list(namespaces=("phases",)))
    assert len(records) == 1
    record = records[0]
    assert record.namespace == "phases"
    assert record.kind is MemoryKind.OBSERVATION
    assert record.metadata["promotion_status"] == "not_promoted"
    candidate = record.metadata["knowledge_candidate"]
    assert candidate["claim_key"] == "mission.completed:aether.missions"
    assert record.provenance is not None
    assert record.provenance.source == "test-observer"
    assert len(record.provenance.event_ids) == 1


def test_phase_observer_replays_durable_events(tmp_path: Path) -> None:
    event_bus = EventBus(tmp_path / "events.jsonl")
    fabric = _fabric(tmp_path)
    PhaseObserver(event_bus, fabric, emit_events=False)

    event_bus.emit(
        EventType.SESSION_PERSISTED,
        actor="aether.runtime",
        payload={"session_id": "s.1"},
    )
    event_bus.emit(
        EventType.MEMORY_RECORDED,
        actor="aether.memory",
        payload={"namespace": "episodes"},
    )

    records = asyncio.run(fabric.canonical.list(namespaces=("phases",)))
    assert {record.key for record in records} == {
        "phase:session.persisted:aether.runtime",
        "phase:memory.recorded:aether.memory",
    }
    assert asyncio.run(fabric.canonical.count()) == 2
