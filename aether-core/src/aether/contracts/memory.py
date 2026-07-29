"""Provider-neutral memory contracts owned by Aether Core."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class MemoryKind(StrEnum):
    EPISODE = "episode"
    OBSERVATION = "observation"
    ACTION = "action"
    REFLECTION = "reflection"
    KNOWLEDGE = "knowledge"
    BELIEF = "belief"


@dataclass(frozen=True)
class MemoryProvenance:
    source: str
    observed_at: str
    session_id: str | None = None
    correlation_id: str | None = None
    event_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_links: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemoryRecord:
    """Canonical provider-neutral memory envelope.

    ``key`` and ``value`` remain first for compatibility with pre-v0.6 adapters.
    Provider-specific identifiers must never be written into Core events.
    """

    key: str
    value: Any
    namespace: str = "default"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    record_id: str | None = None
    kind: MemoryKind = MemoryKind.EPISODE
    content: str = ""
    provenance: MemoryProvenance | None = None
    created_at: str | None = None
    content_hash: str | None = None


@dataclass(frozen=True)
class MemoryQuery:
    text: str
    namespaces: tuple[str, ...] = ("episodes", "knowledge")
    session_id: str | None = None
    kinds: tuple[MemoryKind, ...] = field(default_factory=tuple)
    limit: int = 6
    min_score: float = 0.05


@dataclass(frozen=True)
class MemoryHit:
    record: MemoryRecord
    score: float
    provider_id: str
    reasons: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MemoryContext:
    query: MemoryQuery
    hits: tuple[MemoryHit, ...] = field(default_factory=tuple)

    @property
    def empty(self) -> bool:
        return not self.hits


@runtime_checkable
class MemoryProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def store(self, record: MemoryRecord) -> None: ...

    async def recall(self, key: str, namespace: str = "default") -> MemoryRecord | None: ...

    async def search(self, query: str, namespace: str = "default", limit: int = 10) -> Sequence[MemoryRecord]: ...


@runtime_checkable
class MemoryFabricPort(Protocol):
    async def remember(self, record: MemoryRecord) -> MemoryRecord: ...

    async def retrieve(self, query: MemoryQuery) -> MemoryContext: ...

    async def rebuild_index(self) -> int: ...

    async def record_turn(self, *, session_id: str, perception: Any, expression: Any, event_ids: Sequence[str] = ()) -> MemoryRecord: ...

    async def record_action_resume(self, *, session_id: str, approval_id: str, action_result: Any, expression: Any, correlation_id: str | None) -> MemoryRecord: ...
