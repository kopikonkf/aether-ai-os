"""Deterministic capability lifecycle for governed mutation surfaces.

Truth model (project-docs/audit/CAPABILITY_STATE_MAP_V0192.md):

    IMPLEMENTED -> WIRED -> CONFORMED -> ACTIVE -> FOUNDER-PROVEN

- Implemented: contract and code exist.
- Wired: the runtime constructs the component and exposes a reachable path.
- Conformed: the exact adapter/environment passed a live bounded canary.
- Active: configuration enables the component and policy makes it eligible.
- Founder-proven: a real end-to-end user execution produced evidence.

This module is a pure, deterministic state machine plus bounded JSONL
persistence. It does NOT grant authority: Aether governance (ActionGovernor +
Trusted Approval Inbox) remains the sole authority evaluator, exactly as
defined in ADR-0055. This module only records observation-derived status so
that "active because a class exists" is never claimed.

Single-principal gate (ADR-0055 prerequisite 4): a mutation surface may be
FOUNDER-PROVEN for at most one principal, and no second principal may reach
ACTIVE (mutation-eligible) on that surface until the first principal is
FOUNDER-PROVEN.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "aether.capability-lifecycle.v1"

MUTATION_SURFACE_LIVING_MCP = "living-mcp.mutation"
KNOWN_MUTATION_SURFACES: frozenset[str] = frozenset({MUTATION_SURFACE_LIVING_MCP})

STAGES: tuple[str, ...] = ("implemented", "wired", "conformed", "active", "founder-proven")
STAGE_INDEX = {stage: index for index, stage in enumerate(STAGES)}

# Evidence ids required to ADVANCE INTO each stage (in addition to the
# previous stage already being held). Every key must be present and truthy.
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "implemented": ("source_present",),
    "wired": ("runtime_constructed", "path_reachable"),
    "conformed": ("canary_receipt",),
    "active": ("config_enabled", "policy_eligible"),
    "founder-proven": ("founder_acceptance", "end_to_end_receipt"),
}

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")
_SAFE_NOTE = re.compile(r"[\r\n\x00-\x1f]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stage_index(stage: str) -> int:
    return STAGE_INDEX[str(stage).casefold()]


def next_stage(stage: str) -> str | None:
    index = stage_index(stage) + 1
    return STAGES[index] if index < len(STAGES) else None


def validate_surface(surface: str) -> str:
    value = str(surface or "").strip().casefold()
    if value not in KNOWN_MUTATION_SURFACES:
        raise ValueError(f"unknown mutation surface: {surface}")
    return value


def validate_principal(principal_id: str) -> str:
    value = str(principal_id or "").strip().casefold()
    if not value or not _SAFE_ID.match(value) or len(value) > 64:
        raise ValueError(f"invalid principal_id: {principal_id!r}")
    return value


def validate_evidence(stage: str, evidence: Mapping[str, Any] | None) -> tuple[bool, list[str]]:
    """Return (ok, blockers) for the evidence required to enter `stage`."""
    stage = str(stage or "").casefold()
    required = REQUIRED_EVIDENCE.get(stage, ())
    if not required:
        return False, [f"unknown stage: {stage}"]
    evidence = dict(evidence or {})
    blockers = [key for key in required if not evidence.get(key)]
    return (not blockers), blockers


@dataclass(frozen=True)
class LifecycleTransition:
    """One recorded stage advance, immutable once appended."""

    surface: str
    principal_id: str
    from_stage: str
    to_stage: str
    evidence_ids: tuple[str, ...]
    ts: str = field(default_factory=_utc_now)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "principal_id": self.principal_id,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "evidence_ids": list(self.evidence_ids),
            "ts": self.ts,
            "note": self.note,
        }


@dataclass(frozen=True)
class CapabilityLifecycleRecord:
    """Current observed lifecycle stage for (surface, principal)."""

    surface: str
    principal_id: str
    stage: str = "implemented"
    updated_at: str = field(default_factory=_utc_now)
    transitions: tuple[LifecycleTransition, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def founder_proven(self) -> bool:
        return self.stage == "founder-proven"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "surface": self.surface,
            "principal_id": self.principal_id,
            "stage": self.stage,
            "updated_at": self.updated_at,
            "transitions": [t.to_dict() for t in self.transitions],
            "evidence_keys": sorted(str(key) for key in self.evidence.keys()),
        }


class CapabilityLifecycleBlocked(RuntimeError):
    """A lifecycle transition was refused (fail-closed)."""

    def __init__(self, blockers: list[str]):
        self.blockers = tuple(blockers)
        super().__init__("capability lifecycle blocked: " + "; ".join(blockers))


class CapabilityLifecycle:
    """Deterministic tracker for mutation-surface lifecycle per principal.

    Persists an append-only JSONL transition log. State is always recomputed
    from the log (never trusted from a mutable "latest" file).
    """

    def __init__(self, log_path: Path | None = None):
        self.log_path = Path(log_path) if log_path else None
        self._records: dict[tuple[str, str], CapabilityLifecycleRecord] = {}
        if self.log_path is not None:
            self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self.log_path is None or not self.log_path.exists():
            return
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            self._apply_entry(entry)

    def _apply_entry(self, entry: Mapping[str, Any]) -> None:
        surface = validate_surface(entry.get("surface"))
        principal = validate_principal(entry.get("principal_id"))
        key = (surface, principal)
        record = self._records.get(key)
        stage = str(entry.get("to_stage") or "").casefold()
        if record is None:
            self._records[key] = CapabilityLifecycleRecord(
                surface=surface,
                principal_id=principal,
                stage=stage,
                updated_at=str(entry.get("ts") or _utc_now()),
                evidence=dict(entry.get("evidence") or {}),
                transitions=(LifecycleTransition(
                    surface=surface,
                    principal_id=principal,
                    from_stage=str(entry.get("from_stage") or "implemented"),
                    to_stage=stage,
                    evidence_ids=tuple(str(x) for x in entry.get("evidence_ids") or ()),
                    ts=str(entry.get("ts") or _utc_now()),
                    note=entry.get("note"),
                ),),
            )
            return
        history = record.transitions + (LifecycleTransition(
            surface=surface,
            principal_id=principal,
            from_stage=str(entry.get("from_stage") or record.stage),
            to_stage=stage,
            evidence_ids=tuple(str(x) for x in entry.get("evidence_ids") or ()),
            ts=str(entry.get("ts") or _utc_now()),
            note=entry.get("note"),
        ),)
        self._records[key] = CapabilityLifecycleRecord(
            surface=surface,
            principal_id=principal,
            stage=stage,
            updated_at=str(entry.get("ts") or _utc_now()),
            transitions=history,
            evidence=dict(entry.get("evidence") or {}),
        )

    def _append(self, entry: dict[str, Any]) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def record(self, surface: str, principal_id: str) -> CapabilityLifecycleRecord | None:
        return self._records.get((validate_surface(surface), validate_principal(principal_id)))

    def records(self) -> list[CapabilityLifecycleRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def surface_state(self, surface: str) -> dict[str, Any]:
        surface = validate_surface(surface)
        rows = [r.to_dict() for r in self.records() if r.surface == surface]
        founder = [r.principal_id for r in self.records() if r.surface == surface and r.founder_proven]
        return {
            "schema": SCHEMA,
            "surface": surface,
            "principals": rows,
            "founder_proven_principal": founder[0] if founder else None,
        }

    # ------------------------------------------------------------------
    # Transition (fail-closed)
    # ------------------------------------------------------------------
    def advance(
        self,
        *,
        surface: str,
        principal_id: str,
        to_stage: str,
        evidence: Mapping[str, Any] | None = None,
        note: str | None = None,
    ) -> CapabilityLifecycleRecord:
        surface = validate_surface(surface)
        principal = validate_principal(principal_id)
        to_stage = str(to_stage or "").casefold()
        if to_stage not in STAGE_INDEX:
            raise CapabilityLifecycleBlocked([f"unknown stage: {to_stage}"])

        current = self._records.get((surface, principal))
        current_stage = current.stage if current else "implemented"
        if to_stage == current_stage:
            raise CapabilityLifecycleBlocked([f"already at stage: {to_stage}"])

        expected_prev = STAGES[STAGE_INDEX[to_stage] - 1] if STAGE_INDEX[to_stage] > 0 else None
        if expected_prev is None:
            # cannot regress below implemented; only transitions between
            # consecutive stages are legal
            raise CapabilityLifecycleBlocked(["cannot transition below implemented"])
        if current_stage != expected_prev:
            raise CapabilityLifecycleBlocked([f"expected stage '{expected_prev}' but observed '{current_stage}'"])

        ok, blockers = validate_evidence(to_stage, evidence)
        if not ok:
            raise CapabilityLifecycleBlocked([f"missing evidence for '{to_stage}': {b}" for b in blockers])

        gate_blockers = self._single_principal_gate(surface, principal, to_stage)
        if gate_blockers:
            raise CapabilityLifecycleBlocked(gate_blockers)

        transition = LifecycleTransition(
            surface=surface,
            principal_id=principal,
            from_stage=current_stage,
            to_stage=to_stage,
            evidence_ids=tuple(sorted(str(k) for k in (evidence or {}).keys())),
            note=_clean_note(note),
        )
        entry = {**transition.to_dict(), "evidence": _safe_evidence(evidence)}
        self._apply_entry(entry)
        self._append(entry)
        record = self._records[(surface, principal)]
        assert record is not None
        return record

    def _single_principal_gate(self, surface: str, principal: str, to_stage: str) -> list[str]:
        """ADR-0055 P4 gate: at most one founder-proven principal per surface,
        and no second principal becomes ACTIVE until the first is proven."""
        siblings = [r for r in self.records() if r.surface == surface and r.principal_id != principal]
        proven = [r.principal_id for r in siblings if r.founder_proven]
        if to_stage == "founder-proven" and proven:
            return [f"single-principal gate: '{proven[0]}' is already founder-proven on '{surface}'"]
        # The gate applies only once a second principal appears on the same
        # surface. The first principal may advance freely to ACTIVE and then
        # FOUNDER-PROVEN; a second principal must wait until one is proven.
        if siblings and to_stage == "active" and not proven:
            return [f"single-principal gate: no founder-proven principal on '{surface}' yet; second principal cannot become active"]
        return []


def _clean_note(note: str | None) -> str | None:
    if not note:
        return None
    return _SAFE_NOTE.sub(" ", str(note).strip())[:200] or None


def _safe_evidence(evidence: Mapping[str, Any] | None) -> dict[str, Any]:
    """Store evidence markers only — never secret material."""
    return {str(k): True for k in (evidence or {}).keys()}
