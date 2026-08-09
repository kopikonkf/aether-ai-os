"""Platform T0 — phase observation and versioned work packets.

Phase observation turns durable EventBus facts into proposal-only
``knowledge_candidate`` memory records (namespace ``phases``). It never mutates
governance, never self-approves, and never promotes knowledge directly — it only
records candidate evidence for a later governed pipeline.
"""
from __future__ import annotations

from .observer import PhaseObserver
from .work_packet import (
    WorkPacket,
    WorkPacketStatus,
    WorkPacketValidationError,
    build_work_packet,
    work_packet_v1,
)

__all__ = [
    "PhaseObserver",
    "WorkPacket",
    "WorkPacketStatus",
    "WorkPacketValidationError",
    "build_work_packet",
    "work_packet_v1",
]
