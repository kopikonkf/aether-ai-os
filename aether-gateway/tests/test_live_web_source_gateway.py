from __future__ import annotations

from dataclasses import replace

import pytest

from aether.contracts import (
    ContentSnapshot, LiveSourceConfiguration, SourceAdapterManifest, SourceAdapterStatus,
    SourceCapability, SourceHealth, SourceKind,
)
from aether.opportunities import OpportunityIntelligenceEngine, SQLiteOpportunityStore
from aether.web_intelligence import SQLiteWebIntelligenceStore, WebIntelligenceEngine
from aether_gateway.opportunities import SourceCapabilityMesh
from aether_gateway.web_intelligence import AdaptiveSourceDiscovery, LiveWebAcquisitionService, SourceConformanceService


class HealthyAdapter:
    def __init__(self):
        base = SourceAdapterManifest(
            source_id="source.test", adapter_id="adapter.test", name="Test Source", kind=SourceKind.WEB,
            capabilities=(SourceCapability.FETCH, SourceCapability.CRAWL),
            forbidden_capabilities=("private-network", "file-scheme", "credential-export"),
        )
        from aether.contracts import source_manifest_hash
        self._manifest = replace(base, manifest_hash=source_manifest_hash(base))

    @property
    def manifest(self): return self._manifest
    async def health(self):
        return SourceAdapterStatus(self.manifest.source_id, self.manifest.adapter_id, SourceHealth.HEALTHY, "healthy", version="1.0", checked_at="2026-07-28T00:00:00Z")
    async def search(self, query): return ()
    async def fetch(self, hit, query):
        text = "Independent operators report recurring workflow demand and measurable delays."
        return ContentSnapshot(
            source_id=hit.source_id, adapter_id=self.manifest.adapter_id, canonical_url=hit.url,
            title=hit.title, content_text=text, content_type="text/plain", retrieved_at="2026-07-28T00:00:00Z",
            content_hash=__import__("hashlib").sha256(text.encode()).hexdigest(),
            policy_fingerprint=self.manifest.manifest_hash, source_reference=hit.url,
        )


@pytest.mark.asyncio
async def test_live_source_conformance_binds_config_manifest_and_health(tmp_path):
    mesh = SourceCapabilityMesh(); adapter = HealthyAdapter(); mesh.register(adapter)
    engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3"))
    config = engine.configure_source(LiveSourceConfiguration(
        adapter_id=adapter.manifest.adapter_id, source_id=adapter.manifest.source_id,
        endpoint="https://example.com", allowed_domains=("example.com",), credential_handle="vault:test",
    ), principal="founder")
    receipt = await SourceConformanceService(mesh, engine).conform(adapter.manifest.adapter_id, principal="founder", ttl_seconds=3600)
    assert receipt.state.value == "passed"
    assert receipt.configuration_hash == config.configuration_hash
    assert all(check.passed for check in receipt.checks)


def test_adaptive_discovery_proposes_sources_without_activation(tmp_path):
    opportunity_store = SQLiteOpportunityStore(tmp_path / "opportunity.sqlite3")
    engine = OpportunityIntelligenceEngine(opportunity_store)
    text = "Market evidence references https://new-source.example/report and https://new-source.example/data"
    engine.record_snapshot(ContentSnapshot(
        source_id="source.catalog", adapter_id="adapter.catalog", canonical_url="https://catalog.example/item",
        title="Catalog", content_text=text, content_type="text/plain", retrieved_at="2026-07-28T00:00:00Z",
        content_hash=__import__('hashlib').sha256(text.encode()).hexdigest(),
    ))
    web_engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3"))
    items = AdaptiveSourceDiscovery(opportunity_store, web_engine).discover()
    assert items[0].canonical_domain == "new-source.example"
    assert items[0].state.value == "proposed"


@pytest.mark.asyncio
async def test_live_acquisition_requires_passed_exact_conformance_and_records_evidence(tmp_path):
    mesh = SourceCapabilityMesh(); adapter = HealthyAdapter(); mesh.register(adapter)
    opportunity_store = SQLiteOpportunityStore(tmp_path / "opportunities.sqlite3")
    opportunity_engine = OpportunityIntelligenceEngine(opportunity_store)
    web_engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3"))
    web_engine.configure_source(LiveSourceConfiguration(
        adapter_id=adapter.manifest.adapter_id, source_id=adapter.manifest.source_id,
        endpoint="https://example.com", allowed_domains=("example.com",),
    ), principal="founder")
    service = LiveWebAcquisitionService(mesh, web_engine, opportunity_engine)
    with pytest.raises(ValueError, match="conformance"):
        await service.acquire(adapter_id=adapter.manifest.adapter_id, url="https://example.com", title="Example", objective="workflow demand")
    await SourceConformanceService(mesh, web_engine).conform(adapter.manifest.adapter_id, principal="founder")
    result = await service.acquire(adapter_id=adapter.manifest.adapter_id, url="https://example.com", title="Example", objective="workflow demand")
    assert result["conformance_state"] == "passed"
    assert opportunity_store.get_snapshot(result["snapshot"].snapshot_id).canonical_url == "https://example.com"
    assert result["claims"]
