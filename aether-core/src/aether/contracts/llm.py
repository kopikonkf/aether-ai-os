"""Capability-based model provider contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .actions import ActionProposal


@dataclass(frozen=True)
class ModelRequest:
    capability: str
    messages: Sequence[Mapping[str, Any]]
    constraints: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    content: Any
    provider_id: str
    model_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    action_proposals: Sequence[ActionProposal] = field(default_factory=tuple)


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def supports(self, capability: str) -> bool: ...

    async def invoke(self, request: ModelRequest) -> ModelResponse: ...
