"""Runtime boundary contracts.

Aether Core reasons in terms of capabilities and commands. It never imports or
branches on a concrete runtime implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class RuntimeCommand:
    command: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    capability: str | None = None
    correlation_id: str | None = None
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class RuntimeResult:
    ok: bool
    output: Any = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Port implemented by every interchangeable body/runtime adapter."""

    @property
    def adapter_id(self) -> str: ...

    async def capabilities(self) -> set[str]: ...

    async def health(self) -> Mapping[str, Any]: ...

    async def execute(self, command: RuntimeCommand) -> RuntimeResult: ...
