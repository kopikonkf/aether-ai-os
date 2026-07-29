"""Vendor-neutral cognitive response contract for sense adapters."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .senses import Expression, Perception


@runtime_checkable
class CognitivePort(Protocol):
    """Transforms one governed perception into an expression.

    Implementations may use an LLM, a deterministic workflow, a human relay,
    or a runtime adapter. Aether's sense path does not know which provider is
    behind this port.
    """

    @property
    def adapter_id(self) -> str: ...

    async def respond(self, perception: Perception) -> Expression: ...
