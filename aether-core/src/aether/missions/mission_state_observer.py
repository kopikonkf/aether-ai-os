"""Mission-state observer — connects APCB to the canonical Aether mission store.

MISSION-PCP-002 WORK-3 (F-07): APCBDispatcher accepts an `aether_state_observer`
(Callable mission_id -> str) so dispatch/reconcile can honour the LIVE Aether
mission terminal state — APCB must stop when the mission is terminal, never
promote stale artifacts (F-03). This module provides the deterministic
MissionStatus -> APCB string mapping and a builder that reads the live
SQLiteMissionStore.

The mapping is observation-level: an unknown / unreadable state maps to
"unknown" so APCB treats it as non-terminal and never invents Aether state on
its own. The observer must never raise mid-reconcile (a store error degrades to
"unknown" + a log line, keeping the dispatcher running).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from aether.contracts.missions import MissionStatus

if TYPE_CHECKING:
    from aether.missions.store import SQLiteMissionStore

LOG = logging.getLogger(__name__)

# Deterministic MissionStatus -> APCB mission-state string. APCB stops a work
# item when it sees ("terminal", "completed", "failed", "cancelled", "blocked").
_MISSION_STATUS_TO_APCB: dict[MissionStatus, str] = {
    MissionStatus.DRAFT: "draft",
    MissionStatus.REVIEW_REQUIRED: "review-required",
    MissionStatus.APPROVED: "approved",
    MissionStatus.REJECTED: "rejected",
    MissionStatus.RUNNING: "running",
    MissionStatus.WAITING_APPROVAL: "waiting-approval",
    MissionStatus.PAUSED: "paused",
    MissionStatus.COMPLETED: "completed",
    MissionStatus.FAILED: "failed",
    MissionStatus.CANCELLED: "cancelled",
    MissionStatus.STOPPED: "stopped",
}


def mission_status_to_apcb(state: MissionStatus | None) -> str:
    """Map a MissionStatus to the APCB-recognised mission-state string.

    None / an unknown enum value -> "unknown" (observation-level; APCB treats
    it as non-terminal and never fabricates Aether state).
    """
    if state is None:
        return "unknown"
    return _MISSION_STATUS_TO_APCB.get(state, "unknown")


def build_mission_state_observer(
    store: "SQLiteMissionStore",
) -> Callable[[str], str]:
    """Return an AetherStateObserver reading the canonical mission store.

    The returned callable maps mission_id -> APCB state string via
    store.current_status(). An empty mission_id or a store error returns
    "unknown" (never raises, so APCB reconcile cannot crash mid-flight).
    """

    def observe(mission_id: str) -> str:
        if not mission_id:
            return "unknown"
        try:
            return mission_status_to_apcb(store.current_status(mission_id))
        except Exception:  # noqa: BLE001
            LOG.exception(
                "mission_state_observer: store read failed for mission %r; returning unknown",
                mission_id,
            )
            return "unknown"

    return observe
