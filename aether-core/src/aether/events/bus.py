from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aether.utils.ids import new_id
from aether.utils.jsonio import append_jsonl, read_jsonl
from aether.utils.time import utc_now


@dataclass(frozen=True)
class Event:
    event_type: str
    actor: str
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    event_id: str = field(default_factory=lambda: new_id("evt"))
    timestamp: str = field(default_factory=utc_now)
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "severity": self.severity,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Event":
        return Event(
            event_id=data["event_id"],
            event_type=data["event_type"],
            timestamp=data["timestamp"],
            actor=data["actor"],
            severity=data.get("severity", "info"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            payload=data.get("payload", {}),
        )


EventHandler = Callable[[Event], None]


class EventBus:
    """Synchronous event bus with durable JSONL journal."""

    def __init__(self, journal_path: Path):
        self.journal_path = journal_path
        self._handlers: dict[str, list[EventHandler]] = {}
        self._wildcard_handlers: list[EventHandler] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if event_type == "*":
            self._wildcard_handlers.append(handler)
        else:
            self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> Event:
        append_jsonl(self.journal_path, event.to_dict())
        for handler in self._handlers.get(event.event_type, []):
            handler(event)
        for handler in self._wildcard_handlers:
            handler(event)
        return event

    def emit(
        self,
        event_type: str,
        actor: str,
        payload: dict[str, Any] | None = None,
        severity: str = "info",
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> Event:
        return self.publish(Event(
            event_type=event_type,
            actor=actor,
            payload=payload or {},
            severity=severity,
            correlation_id=correlation_id,
            causation_id=causation_id,
        ))

    def replay(self) -> list[Event]:
        return [Event.from_dict(row) for row in read_jsonl(self.journal_path)]
