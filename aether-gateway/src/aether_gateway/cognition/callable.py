"""Small cognition adapters for integration and local verification."""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from aether.contracts.cognition import CognitivePort
from aether.contracts.senses import Expression, Perception

ResponseFunction = Callable[[Perception], Awaitable[Expression]]


class CallableCognitiveAdapter(CognitivePort):
    def __init__(self, responder: ResponseFunction, *, adapter_id: str = "cognition.callable") -> None:
        self._responder = responder
        self._adapter_id = adapter_id

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def respond(self, perception: Perception) -> Expression:
        return await self._responder(perception)


class EchoCognitiveAdapter(CognitivePort):
    """Deterministic smoke-test brain; never used as production cognition."""

    @property
    def adapter_id(self) -> str:
        return "cognition.echo"

    async def respond(self, perception: Perception) -> Expression:
        return Expression(
            modality="speech",
            content=f"Aether received: {perception.content}",
            target=perception.source,
            metadata={"implementation": "deterministic-smoke-test"},
            correlation_id=perception.correlation_id,
        )
