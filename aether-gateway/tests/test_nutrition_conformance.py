from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aether.contracts import (
    ExternalNutritionCandidate,
    LiveSourceConfiguration,
    NutritionActivationState,
    NutritionConformanceState,
    SourceAdapterManifest,
    SourceCapability,
    SourceConformanceCheck,
    SourceConformanceReceipt,
    SourceConformanceState,
    SourceHealth,
    SourceKind,
    source_manifest_hash,
)
from aether.web_intelligence import SQLiteWebIntelligenceStore, WebIntelligenceEngine
from aether_gateway.nutrition import NutritionConformanceService
from aether_gateway.opportunities import SourceCapabilityMesh


class Adapter:
    def __init__(self, *, adapter_id="adapter.recent", capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH), denials=("private-network", "file-scheme", "credential-export")):
        base = SourceAdapterManifest(
            source_id="source.recent",
            adapter_id=adapter_id,
            name="Recent signal fixture",
            kind=SourceKind.SEARCH,
            capabilities=capabilities,
            forbidden_capabilities=denials,
        )
        self._manifest = replace(base, manifest_hash=source_manifest_hash(base))

    @property
    def manifest(self):
        return self._manifest

    async def health(self):
        raise AssertionError("nutrition conformance must use stored exact receipts, not live network")

    async def search(self, query):
        return ()

    async def fetch(self, hit, query):
        raise AssertionError("no live fetch")


def _candidate(adapter_id="adapter.recent") -> ExternalNutritionCandidate:
    return ExternalNutritionCandidate(
        repository="https://example.com/upstream/recent.git",
        commit_sha="a" * 40,
        artifact_path="SKILL.md",
        artifact_hash="b" * 64,
        license="Apache-2.0",
        publisher="fixture",
        requested_source_capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH),
        required_adapter_ids=(adapter_id,),
        normalization_target="recent-signal-research",
        deterministic_checks=("bounded-window",),
        heldout_checks=("contradiction-case",),
        network_destinations=("https://example.com",),
        activation_state=NutritionActivationState.NORMALIZED,
    )


def _engine(tmp_path, adapter: Adapter, *, receipt_state=SourceConformanceState.PASSED, manifest_hash=None, expires_delta=timedelta(hours=1)):
    engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3"))
    config = engine.configure_source(
        LiveSourceConfiguration(
            adapter_id=adapter.manifest.adapter_id,
            source_id=adapter.manifest.source_id,
            endpoint="https://example.com",
            allowed_domains=("example.com",),
        ),
        principal="founder",
    )
    now = datetime.now(timezone.utc)
    engine.record_conformance(SourceConformanceReceipt(
        adapter_id=adapter.manifest.adapter_id,
        source_id=adapter.manifest.source_id,
        configuration_hash=config.configuration_hash,
        manifest_hash=manifest_hash or adapter.manifest.manifest_hash,
        adapter_version="fixture-v1",
        state=receipt_state,
        checks=(SourceConformanceCheck("fixture", receipt_state == SourceConformanceState.PASSED, "fixture"),),
        issued_by="founder",
        issued_at=now.isoformat().replace("+00:00", "Z"),
        expires_at=(now + expires_delta).isoformat().replace("+00:00", "Z"),
    ))
    return engine


def test_exact_conformed_adapters_make_candidate_benchmark_eligible_but_not_active(tmp_path) -> None:
    adapter = Adapter()
    mesh = SourceCapabilityMesh(); mesh.register(adapter)
    engine = _engine(tmp_path, adapter)

    receipt = NutritionConformanceService(mesh, engine).conform(_candidate(), principal="founder")

    assert receipt.state == NutritionConformanceState.PASSED
    assert receipt.eligible_for_benchmark is True
    assert receipt.eligible_for_activation is False
    assert receipt.required_adapter_manifest_hashes == {adapter.manifest.adapter_id: adapter.manifest.manifest_hash}
    assert len(receipt.source_conformance_receipt_ids) == 1
    assert len(receipt.receipt_hash) == 64


def test_missing_or_stale_adapter_conformance_fails(tmp_path) -> None:
    adapter = Adapter(); mesh = SourceCapabilityMesh(); mesh.register(adapter)
    engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "missing.sqlite3"))
    missing = NutritionConformanceService(mesh, engine).conform(_candidate(), principal="founder")
    assert missing.state == NutritionConformanceState.FAILED
    assert "adapter:adapter.recent:exact-conformance" in (missing.error or "")

    stale_engine = _engine(tmp_path / "stale", adapter, manifest_hash="f" * 64)
    stale = NutritionConformanceService(mesh, stale_engine).conform(_candidate(), principal="founder")
    assert stale.state == NutritionConformanceState.FAILED


def test_adapter_policy_and_capability_mismatch_fail(tmp_path) -> None:
    adapter = Adapter(capabilities=(SourceCapability.FETCH,), denials=("file-scheme",))
    mesh = SourceCapabilityMesh(); mesh.register(adapter)
    engine = _engine(tmp_path, adapter)

    receipt = NutritionConformanceService(mesh, engine).conform(_candidate(), principal="founder")

    assert receipt.state == NutritionConformanceState.FAILED
    failed = {check.name for check in receipt.checks if not check.passed}
    assert "adapter:adapter.recent:mandatory-denials" in failed
    assert "requested-capability-coverage" in failed


def test_unregistered_adapter_fails_without_network_or_state_mutation(tmp_path) -> None:
    mesh = SourceCapabilityMesh()
    engine = WebIntelligenceEngine(SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3"))
    receipt = NutritionConformanceService(mesh, engine).conform(_candidate("adapter.missing"), principal="founder")
    assert receipt.state == NutritionConformanceState.FAILED
    assert any(check.name == "adapter:adapter.missing:registered" for check in receipt.checks)
