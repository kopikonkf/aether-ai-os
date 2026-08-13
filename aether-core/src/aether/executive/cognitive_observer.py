"""CognitiveObserver — deterministic OBSERVE layer for the Aether Cognitive Executive.

Gate 4 closed-loop proof (MISSION-PCP-003 WORK-1): the observe step must read
canonical Aether state — mission store + APCB receipt store + workspace
artifacts — and produce a deterministic snapshot, without dispatching, without
writing, and without ever crashing the loop (fail-soft).

The observer is strictly read-only (NON-ACTIVATION): it never mutates a store
and never talks to Herdr.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aether.contracts.missions import MissionStepStatus
from aether.utils.time import utc_now

if TYPE_CHECKING:
    from aether.apcb.receipt_store import ReceiptStore
    from aether.missions.store import SQLiteMissionStore

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class CognitiveObservation:
    """Immutable snapshot of canonical Aether state at one observed instant."""

    observed_at: str
    mission_states: tuple[dict[str, Any], ...] = ()
    receipt_states: tuple[dict[str, Any], ...] = ()
    reconcile_notes: tuple[dict[str, Any], ...] = ()
    workspace_artifacts: tuple[str, ...] = ()
    summary: str = ""


class CognitiveObserver:
    """Read-only observer over mission store, APCB receipt store, and workspace.

    Every store is optional; a store passed as None simply contributes an empty
    field (not an error). A store read error degrades the affected field to an
    empty tuple and flags the summary with "observe_degraded" — the observer
    never raises, so the Cognitive Executive loop can never be crashed by the
    observe step.
    """

    def __init__(
        self,
        mission_store: "SQLiteMissionStore | None" = None,
        receipt_store: "ReceiptStore | None" = None,
        workspace: str | None = None,
    ) -> None:
        self._mission_store = mission_store
        self._receipt_store = receipt_store
        self._workspace = Path(workspace) if workspace else None
        self._degraded = False

    def observe(self) -> CognitiveObservation:
        self._degraded = False
        mission_states = self._observe_mission_states()
        receipt_states = self._observe_receipt_states()
        reconcile_notes = self._observe_reconcile_notes()
        workspace_artifacts = self._observe_workspace_artifacts()
        return CognitiveObservation(
            observed_at=utc_now(),
            mission_states=mission_states,
            receipt_states=receipt_states,
            reconcile_notes=reconcile_notes,
            workspace_artifacts=workspace_artifacts,
            summary=self._build_summary(
                mission_states, receipt_states, reconcile_notes, workspace_artifacts
            ),
        )

    # ------------------------------------------------------------------ #
    # Mission state                                                      #
    # ------------------------------------------------------------------ #
    def _observe_mission_states(self) -> tuple[dict[str, Any], ...]:
        if self._mission_store is None:
            return ()
        store = self._mission_store
        try:
            states: list[dict[str, Any]] = []
            for plan in store.list_plans():
                mission_id = plan.mission_id
                status = store.current_status(mission_id)
                attempts = store.attempts(mission_id)
                outcome = store.latest_outcome(mission_id)
                completed_steps = {
                    attempt.step_id
                    for attempt in attempts
                    if attempt.status == MissionStepStatus.COMPLETED
                }
                latest = attempts[-1] if attempts else None
                states.append(
                    {
                        "mission_id": mission_id,
                        "status": status.value if status is not None else None,
                        "step_count": len(plan.steps),
                        "completed_steps": len(completed_steps),
                        "attempt_count": len(attempts),
                        "latest_attempt_status": (
                            latest.status.value if latest is not None else None
                        ),
                        "latest_outcome_state": (
                            outcome.state.value if outcome is not None else None
                        ),
                    }
                )
            states.sort(key=lambda item: item["mission_id"])
            return tuple(states)
        except Exception:  # noqa: BLE001 — never crash the Cognitive Executive loop
            LOG.exception("cognitive_observer: mission store read failed; degrading")
            self._degraded = True
            return ()

    # ------------------------------------------------------------------ #
    # APCB receipts + reconcile notes                                    #
    # ------------------------------------------------------------------ #
    def _observe_receipt_states(self) -> tuple[dict[str, Any], ...]:
        if self._receipt_store is None:
            return ()
        try:
            states = [
                {
                    "mission_id": receipt.mission_id,
                    "work_id": receipt.work_id,
                    "attempt_number": receipt.attempt_number,
                    "principal_id": receipt.principal_id,
                    "state": receipt.state.value,
                    "terminal_outcome": receipt.terminal_outcome,
                    "error": receipt.error,
                }
                for receipt in self._receipt_store.all()
            ]
            states.sort(
                key=lambda item: (
                    item["mission_id"],
                    item["work_id"],
                    item["attempt_number"],
                    item["principal_id"],
                )
            )
            return tuple(states)
        except Exception:  # noqa: BLE001
            LOG.exception("cognitive_observer: receipt store read failed; degrading")
            self._degraded = True
            return ()

    def _observe_reconcile_notes(self) -> tuple[dict[str, Any], ...]:
        if self._receipt_store is None:
            return ()
        try:
            notes = [
                {
                    "recorded_at": note.get("recorded_at"),
                    "note_type": note.get("note_type"),
                    "work_id": note.get("work_id"),
                    "mission_id": note.get("mission_id"),
                    "principal_id": note.get("principal_id"),
                    "attempt_number": note.get("attempt_number"),
                    "new_terminal_outcome": note.get("new_terminal_outcome"),
                }
                for note in self._receipt_store.notes()
            ]
            notes.sort(
                key=lambda item: (
                    item["recorded_at"] or "",
                    item["note_type"] or "",
                    item["work_id"] or "",
                    item["mission_id"] or "",
                )
            )
            return tuple(notes)
        except Exception:  # noqa: BLE001
            LOG.exception("cognitive_observer: reconcile notes read failed; degrading")
            self._degraded = True
            return ()

    # ------------------------------------------------------------------ #
    # Workspace artifacts                                                #
    # ------------------------------------------------------------------ #
    def _observe_workspace_artifacts(self) -> tuple[str, ...]:
        if self._workspace is None:
            return ()
        try:
            if not self._workspace.is_dir():
                return ()
            return tuple(
                sorted(
                    entry.name for entry in self._workspace.iterdir() if entry.is_file()
                )
            )
        except Exception:  # noqa: BLE001
            LOG.exception("cognitive_observer: workspace read failed; degrading")
            self._degraded = True
            return ()

    # ------------------------------------------------------------------ #
    # Summary                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _plural(count: int) -> str:
        return "s" if count != 1 else ""

    def _build_summary(
        self,
        mission_states: tuple[dict[str, Any], ...],
        receipt_states: tuple[dict[str, Any], ...],
        reconcile_notes: tuple[dict[str, Any], ...],
        workspace_artifacts: tuple[str, ...],
    ) -> str:
        summary = (
            f"{len(mission_states)} mission{self._plural(len(mission_states))}, "
            f"{len(receipt_states)} receipt{self._plural(len(receipt_states))}, "
            f"{len(reconcile_notes)} note{self._plural(len(reconcile_notes))}, "
            f"{len(workspace_artifacts)} artifact{self._plural(len(workspace_artifacts))}"
        )
        if self._degraded:
            summary += ", observe_degraded"
        return summary
