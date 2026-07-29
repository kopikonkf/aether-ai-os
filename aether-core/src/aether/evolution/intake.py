"""Failure and capability-gap intake for the internal evolution loop."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from aether.contracts.evolution import EvolutionTrigger, EvolutionTriggerType
from aether.events import Event


_FAILURE_EVENTS = {
    "action.failed",
    "action.retry.blocked",
    "sense.path.failed",
    "runtime.result.failed",
    "evolution.evaluation.failed",
}


def evolution_fingerprint(*, category: str, summary: str, target: str | None = None, details: Mapping[str, Any] | None = None) -> str:
    payload = {
        "category": category.strip().casefold(),
        "summary": " ".join(summary.casefold().split()),
        "target": (target or "").strip().casefold(),
        "details": dict(details or {}),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def trigger_from_event(event: Event) -> EvolutionTrigger | None:
    if event.event_type not in _FAILURE_EVENTS:
        return None
    payload = dict(event.payload)
    summary = str(payload.get("error") or payload.get("reason") or payload.get("message") or event.event_type)
    target = str(payload.get("target") or payload.get("operation") or payload.get("adapter_id") or "")
    fingerprint = str(payload.get("failure_fingerprint") or "") or evolution_fingerprint(
        category=event.event_type,
        summary=summary,
        target=target,
        details={"error_type": payload.get("error_type")},
    )
    return EvolutionTrigger(
        trigger_type=EvolutionTriggerType.FAILURE,
        fingerprint=fingerprint,
        summary=summary,
        evidence_ids=(event.event_id,),
        metadata={
            "event_type": event.event_type,
            "actor": event.actor,
            "severity": event.severity,
            "correlation_id": event.correlation_id,
            "target": target,
        },
    )


def capability_gap(*, summary: str, target: str, evidence_ids: tuple[str, ...] = (), metadata: Mapping[str, Any] | None = None) -> EvolutionTrigger:
    return EvolutionTrigger(
        trigger_type=EvolutionTriggerType.CAPABILITY_GAP,
        fingerprint=evolution_fingerprint(category="capability-gap", summary=summary, target=target),
        summary=summary,
        evidence_ids=evidence_ids,
        metadata={"target": target, **dict(metadata or {})},
    )
