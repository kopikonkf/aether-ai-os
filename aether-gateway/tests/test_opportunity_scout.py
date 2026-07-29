from __future__ import annotations

import asyncio

from aether.contracts import (
    ScoutQuery, SourceAdapterManifest, SourceCapability, SourceKind,
)
from aether.opportunities import OpportunityIntelligenceEngine, SQLiteOpportunityStore
from aether_gateway.opportunities import AutonomousOpportunityScout, SourceCapabilityMesh, StaticCatalogAdapter


def test_source_mesh_scout_records_immutable_snapshots_and_claims(tmp_path):
    engine = OpportunityIntelligenceEngine(SQLiteOpportunityStore(tmp_path / "opportunities.sqlite3"))
    mesh = SourceCapabilityMesh()
    for suffix in ("market-a", "market-b"):
        adapter = StaticCatalogAdapter(
            SourceAdapterManifest(
                source_id=f"source.{suffix}", adapter_id=f"adapter.{suffix}", name=suffix,
                kind=SourceKind.CATALOG, capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH, SourceCapability.CATALOG),
                forbidden_capabilities=("credential-export",),
            ),
            ((f"https://example.com/{suffix}", f"Automation demand {suffix}", "Independent operators report recurring automation demand and measurable workflow delays that justify a bounded prototype experiment."),),
        )
        mesh.register(adapter)
        engine.register_source(adapter.manifest)
    scout = AutonomousOpportunityScout(mesh, engine)
    receipt = asyncio.run(scout.run(ScoutQuery(
        objective="workflow automation demand", queries=("automation demand",),
        source_kinds=(SourceKind.CATALOG,), maximum_sources=2, maximum_snapshots=5,
    )))
    assert receipt.status == "completed"
    assert len(receipt.source_ids) == 2
    assert len(receipt.snapshot_ids) == 2
    assert len(receipt.claim_ids) == 2
    assert engine.store.status()["scout_runs"] == 1
