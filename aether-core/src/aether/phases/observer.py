"""T0 phase observer: EventBus facts -> provider-neutral reasoner -> candidate memory.

The observer subscribes to canonical EventBus events, projects each event into a
bounded, deterministic fact, passes it to a provider-neutral reasoner, and
writes a proposal-only ``knowledge_candidate`` memory record in the ``phases``
namespace. It never mutates governance, never self-approves, and never promotes
knowledge directly — promotion stays behind a later governed pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from aether.contracts.event_types import EventType
from aether.contracts.memory import MemoryKind, MemoryProvenance, MemoryRecord
from aether.events import Event, EventBus
from aether.memory import AetherMemoryFabric
from aether.utils.ids import new_id
from aether.utils.time import utc_now

PHASE_NAMESPACE = "phases"


class PhaseReasoner(Protocol):
    """Provider-neutral: project an event fact into a bounded candidate."""

    def project(self, fact: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PhaseObservation:
    event_id: str
    event_type: str
    phase: str
    fact: Mapping[str, Any]
    claim: str
    claim_key: str
    recorded_at: str = field(default_factory=utc_now)


def _deterministic_fact(event: Event) -> Mapping[str, Any]:
    """Project an event into a bounded, stable fact without raw payload secrets."""
    return {
        "event_type": event.event_type,
        "actor": event.actor,
        "severity": event.severity,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "timestamp": event.timestamp,
        "payload_keys": tuple(sorted((event.payload or {}).keys())),
    }


class DefaultPhaseReasoner:
    """Provider-neutral deterministic reasoner.

    Produces a stable candidate claim from the event type and actor, with no
    external model. Keeps the fact bounded and free of payload raw values.
    """

    def project(self, fact: Mapping[str, Any]) -> Mapping[str, Any]:
        event_type = str(fact.get("event_type") or "unknown")
        actor = str(fact.get("actor") or "unknown")
        return {
            "claim": f"{event_type} observed via {actor}",
            "claim_key": f"{event_type}:{actor}",
            "polarity": 0,
            "observation": {
                "event_type": event_type,
                "actor": actor,
                "severity": str(fact.get("severity") or "info"),
            },
        }


class PhaseObserver:
    """Subscribe to an EventBus and record proposal-only phase candidates."""

    def __init__(
        self,
        event_bus: EventBus,
        memory: AetherMemoryFabric,
        *,
        reasoner: PhaseReasoner | None = None,
        subscribe_to: tuple[str, ...] | None = None,
        source: str = "phase-observer",
        emit_events: bool = True,
    ) -> None:
        self.event_bus = event_bus
        self.memory = memory
        self.reasoner = reasoner or DefaultPhaseReasoner()
        self.subscribe_to = subscribe_to or ()
        self.source = source
        self.emit_events = emit_events
        self._in_handler = False
        self._handler = self._on_event
        self._attach()

    def _attach(self) -> None:
        if self.subscribe_to:
            for event_type in self.subscribe_to:
                self.event_bus.subscribe(event_type, self._handler)
        else:
            self.event_bus.subscribe("*", self._handler)

    def _on_event(self, event: Event) -> None:
        if self.subscribe_to and event.event_type not in self.subscribe_to:
            return
        if self._in_handler:
            return
        self._in_handler = True
        try:
            self._record(event)
        finally:
            self._in_handler = False

    def _record(self, event: Event) -> None:
        fact = _deterministic_fact(event)
        projection = self.reasoner.project(fact)
        phase = str(projection.get("claim_key") or event.event_type)
        observation = PhaseObservation(
            event_id=event.event_id,
            event_type=event.event_type,
            phase=phase,
            fact=fact,
            claim=str(projection.get("claim") or event.event_type),
            claim_key=str(projection.get("claim_key") or event.event_type),
        )
        record = MemoryRecord(
            key=f"phase:{observation.claim_key}",
            value={
                "event_id": observation.event_id,
                "event_type": observation.event_type,
                "claim": observation.claim,
                "fact": dict(observation.fact),
            },
            namespace=PHASE_NAMESPACE,
            kind=MemoryKind.OBSERVATION,
            content=observation.claim,
            metadata={
                "knowledge_candidate": {
                    "claim": observation.claim,
                    "claim_key": observation.claim_key,
                    "polarity": int(projection.get("polarity") or 0),
                },
                "promotion_status": "not_promoted",
                "phase": observation.phase,
                "observer": self.source,
            },
            provenance=MemoryProvenance(
                source=self.source,
                observed_at=observation.recorded_at,
                event_ids=(observation.event_id,),
            ),
        )
        self.memory.canonical.append_sync(record)
        if self.emit_events:
            self.event_bus.emit(
                EventType.MEMORY_RECORDED,
                actor=self.source,
                payload={
                    "namespace": PHASE_NAMESPACE,
                    "kind": MemoryKind.OBSERVATION.value,
                    "claim_key": observation.claim_key,
                    "phase": observation.phase,
                },
                correlation_id=event.correlation_id,
            )
