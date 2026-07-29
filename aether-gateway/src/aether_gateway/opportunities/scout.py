"""Autonomous bounded scout loop: source mesh -> snapshots -> claims -> candidate evidence."""
from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from typing import Sequence

from aether.contracts.event_types import EventType
from aether.contracts.opportunities import (
    ClaimExtractor, ClaimStance, ContentSnapshot, EvidenceStrength, ExtractedClaim,
    ScoutQuery, ScoutRunReceipt, SourceAdapterStatus, SourceHealth,
)
from aether.events import EventBus
from aether.opportunities import OpportunityIntelligenceEngine
from aether.utils.time import utc_now
from aether_gateway.opportunities.adapters import SourceCapabilityMesh


class HeuristicOpportunityClaimExtractor:
    """Deterministic reference extractor. A model-backed extractor can replace it via the same port."""

    extractor_id = "aether.extractor.heuristic-opportunity-v1"

    async def extract(self, snapshot: ContentSnapshot, query: ScoutQuery) -> Sequence[ExtractedClaim]:
        lines = [" ".join(line.strip().split()) for line in snapshot.content_text.splitlines()]
        lines = [line for line in lines if 30 <= len(line) <= 500]
        tokens = {token.casefold() for value in query.queries for token in value.split() if len(token) > 3}
        selected = [line for line in lines if not tokens or any(token in line.casefold() for token in tokens)][:8]
        out = []
        for line in selected:
            normalized = line.casefold()
            contradicts = any(term in normalized for term in ("no demand", "declining", "failed", "not needed", "saturated"))
            strength = EvidenceStrength.MODERATE if snapshot.metadata.get("catalog") else EvidenceStrength.STRONG
            out.append(ExtractedClaim(
                snapshot_id=snapshot.snapshot_id, source_id=snapshot.source_id, statement=line,
                stance=ClaimStance.CONTRADICTS if contradicts else ClaimStance.SUPPORTS,
                subject=query.objective, confidence=0.68 if strength == EvidenceStrength.MODERATE else 0.72,
                evidence_strength=strength, observed_at=snapshot.retrieved_at,
                external_reference=snapshot.canonical_url, extractor_id=self.extractor_id,
                metadata={"deterministic": True},
            ))
        return tuple(out)


class AutonomousOpportunityScout:
    scout_id = "aether.opportunity-scout"

    def __init__(
        self, mesh: SourceCapabilityMesh, engine: OpportunityIntelligenceEngine,
        *, extractor: ClaimExtractor | None = None, event_bus: EventBus | None = None,
    ) -> None:
        self.mesh = mesh
        self.engine = engine
        self.extractor = extractor or HeuristicOpportunityClaimExtractor()
        self.event_bus = event_bus

    async def run(self, query: ScoutQuery) -> ScoutRunReceipt:
        started_at = utc_now()
        started = time.perf_counter()
        self._emit(EventType.OPPORTUNITY_SCOUT_STARTED, {
            "query_id": query.query_id, "objective": query.objective,
            "autonomy_level": query.autonomy_level.value, "queries": list(query.queries),
        })
        statuses = await self.mesh.status()
        for status in statuses:
            self.engine.record_source_status(status)
        adapters = await self.mesh.eligible(query)
        snapshots = []
        claims = []
        blockers: list[str] = []
        bytes_consumed = 0
        for adapter in adapters:
            if len(snapshots) >= query.maximum_snapshots:
                break
            try:
                hits = await adapter.search(query)
            except Exception as exc:
                blockers.append(f"{adapter.manifest.adapter_id} search failed: {exc}")
                continue
            for hit in hits:
                if len(snapshots) >= query.maximum_snapshots:
                    break
                if time.perf_counter() - started > query.maximum_duration_seconds:
                    blockers.append("scout duration budget reached")
                    break
                try:
                    snapshot = await adapter.fetch(hit, query)
                    size = len(snapshot.content_text.encode("utf-8"))
                    if bytes_consumed + size > query.maximum_bytes:
                        blockers.append("scout byte budget reached")
                        break
                    saved_snapshot = self.engine.record_snapshot(snapshot)
                    snapshots.append(saved_snapshot)
                    bytes_consumed += size
                    for claim in await self.extractor.extract(saved_snapshot, query):
                        claims.append(self.engine.record_claim(claim))
                except Exception as exc:
                    blockers.append(f"{adapter.manifest.adapter_id} fetch failed for {hit.url}: {exc}")
        status = "completed" if snapshots else "blocked"
        receipt = ScoutRunReceipt(
            query_id=query.query_id, status=status,
            source_ids=tuple(sorted({item.source_id for item in snapshots})),
            snapshot_ids=tuple(item.snapshot_id for item in snapshots), claim_ids=tuple(item.claim_id for item in claims),
            candidate_ids=(), bytes_consumed=bytes_consumed,
            duration_seconds=round(time.perf_counter() - started, 6), blockers=tuple(blockers),
            metadata={"adapter_ids": [item.manifest.adapter_id for item in adapters], "extractor_id": self.extractor.extractor_id},
            started_at=started_at, completed_at=utc_now(),
        )
        saved = self.engine.store.add_run(receipt)
        self._emit(EventType.OPPORTUNITY_SCOUT_COMPLETED, {
            "run_id": saved.run_id, "query_id": query.query_id, "status": saved.status,
            "source_count": len(saved.source_ids), "snapshot_count": len(saved.snapshot_ids),
            "claim_count": len(saved.claim_ids), "bytes_consumed": saved.bytes_consumed,
            "blockers": list(saved.blockers),
        }, severity="warning" if saved.status != "completed" else "info")
        return saved

    def _emit(self, event_type: EventType, payload: dict, severity: str = "info") -> None:
        if self.event_bus:
            self.event_bus.emit(event_type.value, actor=self.scout_id, payload=payload, severity=severity)
