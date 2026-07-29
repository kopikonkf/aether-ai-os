"""Request/response sense adapter for HTTP, CLI, and desktop shells."""
from __future__ import annotations

from collections.abc import AsyncIterator

from aether.contracts.senses import Expression, Perception, SenseAdapter


class DirectTextSenseAdapter(SenseAdapter):
    def __init__(self, *, adapter_id: str = "sense.direct-text") -> None:
        self._adapter_id = adapter_id
        self.expressions: list[Expression] = []

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def perceive(self) -> AsyncIterator[Perception]:
        if False:  # pragma: no cover - protocol-compatible empty iterator
            yield Perception(modality="text", content="", source="unused")

    async def express(self, expression: Expression) -> None:
        self.expressions.append(expression)
