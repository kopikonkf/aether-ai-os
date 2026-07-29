from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from aether.contracts import (
    ContentSnapshot, EvidenceFreshnessPolicy, FreshnessState, LiveSourceConfiguration,
    SourceConformanceCheck, SourceConformanceReceipt, SourceConformanceState,
    SourceDiscoveryCandidate, SourceDiscoveryState, WebIntelligenceBlocked,
)
from aether.web_intelligence import SQLiteWebIntelligenceStore, WebIntelligenceEngine


def make_engine(tmp_path):
    store = SQLiteWebIntelligenceStore(tmp_path / "web.sqlite3")
    return WebIntelligenceEngine(store), store


def configure(engine, **changes):
    values = dict(
        adapter_id="source.adapter.crawl4ai-restricted", source_id="source.web.crawl4ai",
        endpoint="https://example.com", allowed_domains=("example.com",), maximum_pages=5,
        maximum_depth=2, maximum_bytes=100_000, timeout_seconds=30,
    )
    values.update(changes)
    return engine.configure_source(LiveSourceConfiguration(**values), principal="founder")


def test_live_source_configuration_is_trusted_versioned_and_append_only(tmp_path):
    engine, store = make_engine(tmp_path)
    with pytest.raises(WebIntelligenceBlocked, match="trusted"):
        engine.configure_source(LiveSourceConfiguration(
            adapter_id="a", source_id="s", endpoint="https://example.com",
            allowed_domains=("example.com",),
        ), principal="model")
    first = configure(engine)
    second = configure(engine, maximum_pages=6)
    assert first.configuration_hash != second.configuration_hash
    assert store.latest_configuration(first.adapter_id).configuration_hash == second.configuration_hash
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE live_source_configurations SET payload_json='changed'")


def test_conformance_is_exact_and_becomes_stale_after_configuration_change(tmp_path):
    engine, _ = make_engine(tmp_path)
    config = configure(engine)
    receipt = engine.record_conformance(SourceConformanceReceipt(
        adapter_id=config.adapter_id, source_id=config.source_id,
        configuration_hash=config.configuration_hash, manifest_hash="manifest-a", adapter_version="0.9",
        state=SourceConformanceState.PASSED,
        checks=(SourceConformanceCheck("health", True, "healthy"),),
        issued_by="founder", issued_at="2026-07-28T00:00:00Z", expires_at="2026-07-29T00:00:00Z",
    ))
    assert receipt.receipt_hash
    assert engine.effective_conformance(config.adapter_id, manifest_hash="manifest-a", now="2026-07-28T01:00:00Z") == SourceConformanceState.PASSED
    configure(engine, maximum_pages=9)
    assert engine.effective_conformance(config.adapter_id, manifest_hash="manifest-a", now="2026-07-28T01:00:00Z") == SourceConformanceState.STALE


def test_freshness_decay_preserves_snapshot_and_creates_refresh_evidence(tmp_path):
    engine, store = make_engine(tmp_path)
    snapshot = ContentSnapshot(
        source_id="source.web", adapter_id="adapter.web", canonical_url="https://example.com/a",
        title="A", content_text="evidence", content_type="text/plain",
        retrieved_at="2026-07-20T00:00:00Z", content_hash="abc",
    )
    record = engine.evaluate_freshness(
        snapshot, EvidenceFreshnessPolicy(fresh_for_seconds=60, aging_for_seconds=120),
        evaluated_at="2026-07-28T00:00:00Z",
    )
    assert record.state == FreshnessState.STALE
    assert record.refresh_required is True
    assert store.latest_freshness(snapshot.snapshot_id).content_hash == "abc"


def test_adaptive_discovery_is_proposal_until_trusted_decision(tmp_path):
    engine, store = make_engine(tmp_path)
    item = engine.propose_source(SourceDiscoveryCandidate(
        discovered_url="https://market.example", canonical_domain="", discovered_from_snapshot_ids=("snapshot-1",),
        capabilities=("fetch", "crawl"), reason="Observed in source evidence.", confidence=0.7, risk="low",
    ))
    assert item.state == SourceDiscoveryState.PROPOSED
    with pytest.raises(WebIntelligenceBlocked, match="trusted"):
        engine.decide_source(item.candidate_id, state=SourceDiscoveryState.ACCEPTED, principal="model", reason="Model activates it.")
    decision = engine.decide_source(
        item.candidate_id, state=SourceDiscoveryState.ACCEPTED, principal="founder",
        reason="The source is public, relevant, and will enter conformance before activation.",
    )
    assert decision.state == SourceDiscoveryState.ACCEPTED
    assert len(store.discoveries()) == 2
