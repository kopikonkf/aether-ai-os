"""End-to-end event path from perception to expression."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from aether.contracts.cognition import CognitivePort
from aether.contracts.event_types import EventType
from aether.contracts.senses import Expression, Perception, SenseAdapter
from aether.events import EventBus
from aether.utils.ids import new_id


@dataclass(frozen=True)
class SensePathResult:
    """Trace identifiers for one completed perception/expression turn."""

    correlation_id: str
    perception_event_id: str
    cognition_event_id: str
    cognition_completed_event_id: str
    expression_event_id: str
    expression_delivered_event_id: str
    sense_adapter_id: str
    cognitive_adapter_id: str


class SenseEventPath:
    """Routes every communication channel through durable Aether semantics."""

    def __init__(self, event_bus: EventBus, cognition: CognitivePort) -> None:
        self.event_bus = event_bus
        self.cognition = cognition

    async def handle(self, sense: SenseAdapter, perception: Perception) -> SensePathResult:
        correlation_id = perception.correlation_id or new_id("corr")
        governed_perception = replace(perception, correlation_id=correlation_id)
        last_event_id: str | None = None

        try:
            perception_event = self.event_bus.emit(
                event_type=EventType.PERCEPTION_RECEIVED,
                actor=sense.adapter_id,
                payload=self._perception_event_payload(governed_perception),
                correlation_id=correlation_id,
            )
            last_event_id = perception_event.event_id

            cognition_event = self.event_bus.emit(
                event_type=EventType.COGNITION_REQUESTED,
                actor="aether.sense-path",
                payload={
                    "cognitive_adapter_id": self.cognition.adapter_id,
                    "perception_event_id": perception_event.event_id,
                    "modality": governed_perception.modality,
                    "source": governed_perception.source,
                },
                correlation_id=correlation_id,
                causation_id=perception_event.event_id,
            )
            last_event_id = cognition_event.event_id

            expression = await self.cognition.respond(governed_perception)
            governed_expression = replace(expression, correlation_id=correlation_id)

            cognition_completed = self.event_bus.emit(
                event_type=EventType.COGNITION_COMPLETED,
                actor=self.cognition.adapter_id,
                payload={
                    "cognition_event_id": cognition_event.event_id,
                    "expression_modality": governed_expression.modality,
                    "target": governed_expression.target,
                    "provider_id": governed_expression.metadata.get("provider_id"),
                    "model_id": governed_expression.metadata.get("model_id"),
                },
                correlation_id=correlation_id,
                causation_id=cognition_event.event_id,
            )
            last_event_id = cognition_completed.event_id

            expression_event = self.event_bus.emit(
                event_type=EventType.EXPRESSION_REQUESTED,
                actor=self.cognition.adapter_id,
                payload=asdict(governed_expression),
                correlation_id=correlation_id,
                causation_id=cognition_completed.event_id,
            )
            last_event_id = expression_event.event_id

            await sense.express(governed_expression)

            delivered_event = self.event_bus.emit(
                event_type=EventType.EXPRESSION_DELIVERED,
                actor=sense.adapter_id,
                payload={
                    "expression_event_id": expression_event.event_id,
                    "modality": governed_expression.modality,
                    "target": governed_expression.target,
                },
                correlation_id=correlation_id,
                causation_id=expression_event.event_id,
            )

            return SensePathResult(
                correlation_id=correlation_id,
                perception_event_id=perception_event.event_id,
                cognition_event_id=cognition_event.event_id,
                cognition_completed_event_id=cognition_completed.event_id,
                expression_event_id=expression_event.event_id,
                expression_delivered_event_id=delivered_event.event_id,
                sense_adapter_id=sense.adapter_id,
                cognitive_adapter_id=self.cognition.adapter_id,
            )
        except Exception as exc:
            self.event_bus.emit(
                event_type=EventType.SENSE_PATH_FAILED,
                actor="aether.sense-path",
                payload={
                    "sense_adapter_id": sense.adapter_id,
                    "cognitive_adapter_id": self.cognition.adapter_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                severity="error",
                correlation_id=correlation_id,
                causation_id=last_event_id,
            )
            raise

    @staticmethod
    def _perception_event_payload(perception: Perception) -> dict[str, Any]:
        payload = asdict(perception)
        if perception.modality.startswith("image.") or perception.modality.startswith("audio.raw"):
            payload["content"] = "<redacted-media>"
            payload["media"] = {
                "content_hash": perception.metadata.get("media_content_hash"),
                "byte_count": perception.metadata.get("media_byte_count"),
                "content_type": perception.metadata.get("media_content_type"),
            }
        return payload

    async def run(self, sense: SenseAdapter, *, limit: int | None = None) -> list[SensePathResult]:
        """Consume perceptions until cancelled or the optional limit is met."""

        if limit is not None and limit < 1:
            raise ValueError("limit must be at least 1 when provided")

        results: list[SensePathResult] = []
        async for perception in sense.perceive():
            results.append(await self.handle(sense, perception))
            if limit is not None and len(results) >= limit:
                break
        return results
