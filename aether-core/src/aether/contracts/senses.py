"""Perception and communication adapter contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class Perception:
    modality: str
    content: Any
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(frozen=True)
class Expression:
    modality: str
    content: Any
    target: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@runtime_checkable
class SenseAdapter(Protocol):
    """Port for voice, camera, Telegram, browser, robot, or future senses."""

    @property
    def adapter_id(self) -> str: ...

    async def perceive(self) -> AsyncIterator[Perception]: ...

    async def express(self, expression: Expression) -> None: ...
