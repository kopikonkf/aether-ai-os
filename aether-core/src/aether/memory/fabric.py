"""Aether Memory Fabric orchestration."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from aether.contracts.event_types import EventType
from aether.contracts.memory import (
    MemoryContext, MemoryHit, MemoryKind, MemoryProvenance, MemoryQuery, MemoryRecord,
)
from aether.contracts.senses import Expression, Perception
from aether.events import EventBus
from aether.utils.ids import new_id
from aether.utils.time import utc_now

from .canonical import SQLiteCanonicalMemoryStore
from .obsidian import ObsidianMemoryProjector
from .provider import SQLiteLexicalMemoryProvider


class AetherMemoryFabric:
    """Canonical write + rebuildable retrieval + optional human projection."""

    fabric_id = "aether.memory.fabric"

    def __init__(
        self,
        canonical: SQLiteCanonicalMemoryStore,
        retrieval: SQLiteLexicalMemoryProvider,
        *,
        event_bus: EventBus | None = None,
        obsidian: ObsidianMemoryProjector | None = None,
    ) -> None:
        self.canonical = canonical
        self.retrieval = retrieval
        self.event_bus = event_bus
        self.obsidian = obsidian

    async def remember(self, record: MemoryRecord) -> MemoryRecord:
        if record.kind == MemoryKind.BELIEF:
            raise PermissionError("belief writes are outside the Memory Fabric promotion pipeline")
        if record.kind == MemoryKind.KNOWLEDGE:
            governed = bool(record.metadata.get("governance_required"))
            proposal_id = str(record.metadata.get("proposal_id") or "").strip()
            trusted_source = bool(record.provenance and record.provenance.source == "trusted-knowledge-governance")
            if not (governed and proposal_id and trusted_source):
                raise PermissionError(
                    "direct knowledge writes are forbidden; use MemoryCurator.decide()"
                )
        canonical = await self.canonical.append(record)
        await self.retrieval.store(canonical)
        self._emit(
            EventType.MEMORY_RECORDED,
            {
                "record_id": canonical.record_id,
                "namespace": canonical.namespace,
                "kind": canonical.kind.value,
                "content_hash": canonical.content_hash,
                "retrieval_provider": self.retrieval.provider_id,
            },
            correlation_id=canonical.provenance.correlation_id if canonical.provenance else None,
        )
        return canonical

    async def record_turn(
        self,
        *,
        session_id: str,
        perception: Perception,
        expression: Expression,
        event_ids: Sequence[str] = (),
    ) -> MemoryRecord:
        media_modality = perception.modality.startswith("image.") or perception.modality.startswith("audio.raw")
        persisted_perception_content = (
            {
                "redacted_media": True,
                "content_hash": perception.metadata.get("media_content_hash"),
                "byte_count": perception.metadata.get("media_byte_count"),
                "content_type": perception.metadata.get("media_content_type"),
                "prompt": perception.content.get("prompt") if isinstance(perception.content, dict) else None,
            }
            if media_modality else perception.content
        )
        value = {
            "perception": {
                "modality": perception.modality,
                "content": persisted_perception_content,
                "source": perception.source,
                "metadata": dict(perception.metadata),
            },
            "expression": {
                "modality": expression.modality,
                "content": expression.content,
                "target": expression.target,
                "metadata": dict(expression.metadata),
            },
        }
        perception_summary = (
            str(persisted_perception_content.get("prompt") or "[media perception]")
            if isinstance(persisted_perception_content, dict) and persisted_perception_content.get("redacted_media")
            else str(persisted_perception_content).strip()
        )
        content = (
            f"User: {perception_summary}\n"
            f"Aether: {str(expression.content).strip()}"
        )
        return await self.remember(MemoryRecord(
            key=new_id("turn"),
            value=value,
            namespace="episodes",
            kind=MemoryKind.EPISODE,
            content=content,
            metadata={
                "session_id": session_id,
                "channel": perception.metadata.get("channel"),
                "provider_id": expression.metadata.get("provider_id"),
                "model_id": expression.metadata.get("model_id"),
                "action_results": expression.metadata.get("action_results", []),
            },
            provenance=MemoryProvenance(
                source=perception.source,
                observed_at=utc_now(),
                session_id=session_id,
                correlation_id=perception.correlation_id or expression.correlation_id,
                event_ids=tuple(event_ids),
            ),
        ))

    async def record_action_resume(
        self,
        *,
        session_id: str,
        approval_id: str,
        action_result: Any,
        expression: Expression,
        correlation_id: str | None,
    ) -> MemoryRecord:
        return await self.remember(MemoryRecord(
            key=f"approval:{approval_id}",
            value={
                "approval_id": approval_id,
                "action_result": asdict(action_result),
                "expression": str(expression.content),
            },
            namespace="episodes",
            kind=MemoryKind.ACTION,
            content=(
                f"Approved action {approval_id} result: status={action_result.status}, "
                f"ok={action_result.ok}. Aether: {str(expression.content).strip()}"
            ),
            metadata={"session_id": session_id, "approval_id": approval_id},
            provenance=MemoryProvenance(
                source="trusted-approval",
                observed_at=utc_now(),
                session_id=session_id,
                correlation_id=correlation_id,
            ),
        ))

    async def retrieve(self, query: MemoryQuery) -> MemoryContext:
        ranked = await self.retrieval.search_scored(
            query.text,
            namespaces=query.namespaces,
            limit=max(query.limit * 3, query.limit),
        )
        hits: list[MemoryHit] = []
        for record, score, reasons in ranked:
            if query.kinds and record.kind not in query.kinds:
                continue
            if score < query.min_score:
                continue
            hits.append(MemoryHit(record, score, self.retrieval.provider_id, reasons))
            if len(hits) >= query.limit:
                break
        context = MemoryContext(query, tuple(hits))
        self._emit(
            EventType.MEMORY_RETRIEVED,
            {
                "query": query.text,
                "session_id": query.session_id,
                "hit_count": len(hits),
                "record_ids": [item.record.record_id for item in hits],
            },
        )
        return context

    async def rebuild_index(self) -> int:
        count = await self.retrieval.rebuild()
        self._emit(EventType.MEMORY_INDEX_REBUILT, {
            "record_count": count,
            "provider_id": self.retrieval.provider_id,
        })
        return count

    async def project_session(self, session_id: str) -> str | None:
        if self.obsidian is None:
            return None
        records = await self.canonical.list(namespaces=("episodes",))
        selected = [
            record for record in records
            if record.provenance and record.provenance.session_id == session_id
        ]
        path = await self.obsidian.project_session(session_id, selected)
        self._emit(EventType.MEMORY_PROJECTED, {
            "session_id": session_id,
            "record_count": len(selected),
            "path": str(path),
            "authority": "projection_only",
        })
        return str(path)

    async def stats(self) -> dict[str, Any]:
        return {
            "fabric_id": self.fabric_id,
            "canonical_provider": self.canonical.provider_id,
            "retrieval_provider": self.retrieval.provider_id,
            "canonical_records": await self.canonical.count(),
            "indexed_records": await self.retrieval.count(),
            "obsidian_projection_enabled": self.obsidian is not None,
        }

    def _emit(self, event_type: str, payload: dict[str, Any], correlation_id: str | None = None) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(
                event_type=event_type,
                actor=self.fabric_id,
                payload=payload,
                correlation_id=correlation_id,
            )
