"""Live source conformance, freshness scheduling, and adaptive discovery."""
from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from aether.contracts import (
    AutonomyLevel, ContentSnapshot, EvidenceFreshnessPolicy, LiveSourceConfiguration,
    ScoutQuery, SearchHit, SourceConformanceCheck, SourceConformanceReceipt, SourceConformanceState,
    SourceDiscoveryCandidate, SourceDiscoveryState, SourceHealth,
)
from aether.opportunities import SQLiteOpportunityStore
from aether.utils.time import utc_now
from aether.web_intelligence import WebIntelligenceEngine
from aether_gateway.opportunities import HeuristicOpportunityClaimExtractor, SourceCapabilityMesh


class SourceConformanceService:
    """Issues exact receipts from live adapter health and restricted-policy evidence."""

    def __init__(self, mesh: SourceCapabilityMesh, engine: WebIntelligenceEngine) -> None:
        self.mesh = mesh
        self.engine = engine

    async def conform(self, adapter_id: str, *, principal: str, ttl_seconds: int = 86_400) -> SourceConformanceReceipt:
        adapter = self.mesh.get(adapter_id)
        config = self.engine.store.latest_configuration(adapter_id)
        if config is None:
            raise ValueError(f"source configuration missing for {adapter_id}")
        status = await adapter.health()
        manifest = adapter.manifest
        checks = [
            SourceConformanceCheck("configuration-enabled", config.enabled, "live source configuration is enabled" if config.enabled else "configuration disabled"),
            SourceConformanceCheck("adapter-health", status.health == SourceHealth.HEALTHY, status.reason, {"version": status.version}),
            SourceConformanceCheck("manifest-boundary", bool(manifest.manifest_hash), "adapter manifest has immutable fingerprint"),
            SourceConformanceCheck("domain-allowlist", bool(config.allowed_domains) or config.endpoint.startswith("local:"), "explicit live domain allowlist present"),
            SourceConformanceCheck("credential-isolation", not config.credential_handle or config.credential_handle.startswith(("file:", "env:", "vault:")), "credential is an opaque handle"),
            SourceConformanceCheck("private-network-denial", "private-network" in manifest.forbidden_capabilities, "manifest forbids private network access"),
            SourceConformanceCheck("file-scheme-denial", "file-scheme" in manifest.forbidden_capabilities, "manifest forbids local file scheme"),
        ]
        canary_passed = False
        canary_detail = "live canary was not executed"
        canary_evidence = {}
        if config.enabled and status.health == SourceHealth.HEALTHY and config.endpoint.startswith(("http://", "https://")):
            try:
                snapshot = await adapter.fetch(
                    SearchHit(source_id=config.source_id, url=config.endpoint, title="Aether source conformance canary", snippet="", rank=1, query="source conformance"),
                    ScoutQuery(
                        objective="Verify live source acquisition boundary.", queries=("source conformance",),
                        maximum_sources=1, maximum_snapshots=1, maximum_bytes=config.maximum_bytes,
                        maximum_duration_seconds=config.timeout_seconds, allowed_domains=config.allowed_domains,
                        blocked_domains=config.blocked_domains, autonomy_level=AutonomyLevel.OBSERVE,
                        metadata={"conformance_canary": True},
                    ),
                )
                canary_passed = bool(snapshot.content_text.strip()) and snapshot.status_code < 400
                canary_detail = "live canary acquisition succeeded" if canary_passed else "live canary returned empty or unsuccessful content"
                canary_evidence = {"snapshot_hash": snapshot.content_hash, "status_code": snapshot.status_code, "canonical_url": snapshot.canonical_url}
            except Exception as exc:
                canary_detail = f"{type(exc).__name__}: {exc}"
        checks.append(SourceConformanceCheck("live-canary-acquisition", canary_passed, canary_detail, canary_evidence))
        passed = all(item.passed for item in checks)
        now = datetime.now(timezone.utc)
        receipt = SourceConformanceReceipt(
            adapter_id=manifest.adapter_id, source_id=manifest.source_id,
            configuration_hash=config.configuration_hash, manifest_hash=manifest.manifest_hash,
            adapter_version=status.version or "unknown",
            state=SourceConformanceState.PASSED if passed else SourceConformanceState.FAILED,
            checks=tuple(checks), issued_by=principal,
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=max(60, ttl_seconds))).isoformat().replace("+00:00", "Z"),
            error=None if passed else "; ".join(item.detail for item in checks if not item.passed),
            metadata={"health": status.health.value, "restricted_profile": status.metadata.get("restricted_profile", False), "live_canary": True},
        )
        return self.engine.record_conformance(receipt)



class EvidenceFreshnessScheduler:
    """Evaluates snapshot age and returns a bounded refresh queue; never deletes evidence."""

    def __init__(self, opportunity_store: SQLiteOpportunityStore, engine: WebIntelligenceEngine) -> None:
        self.opportunity_store = opportunity_store
        self.engine = engine

    def run(self, policy: EvidenceFreshnessPolicy, *, evaluated_at: str | None = None) -> dict:
        records = [self.engine.evaluate_freshness(item, policy, evaluated_at=evaluated_at) for item in self.opportunity_store.list_snapshots(limit=5000)]
        refresh = [item for item in records if item.refresh_required][: policy.refresh_batch_size]
        stale = [item for item in records if item.state.value == "stale"]
        fraction = (len(stale) / len(records)) if records else 0.0
        return {
            "evaluated": len(records), "fresh": sum(item.state.value == "fresh" for item in records),
            "aging": sum(item.state.value == "aging" for item in records), "stale": len(stale),
            "stale_fraction": round(fraction, 6),
            "portfolio_refresh_required": fraction > policy.maximum_stale_fraction,
            "refresh_snapshot_ids": [item.snapshot_id for item in refresh],
        }


class LiveWebAcquisitionService:
    """Acquires one live URL only after exact source conformance and records immutable evidence."""

    def __init__(self, mesh: SourceCapabilityMesh, web_engine: WebIntelligenceEngine, opportunity_engine) -> None:
        self.mesh = mesh
        self.web_engine = web_engine
        self.opportunity_engine = opportunity_engine
        self.extractor = HeuristicOpportunityClaimExtractor()

    async def acquire(self, *, adapter_id: str, url: str, title: str, objective: str) -> dict:
        adapter = self.mesh.get(adapter_id)
        config = self.web_engine.store.latest_configuration(adapter_id)
        if config is None or not config.enabled:
            raise ValueError("live source is not configured and enabled")
        state = self.web_engine.effective_conformance(adapter_id, manifest_hash=adapter.manifest.manifest_hash)
        if state != SourceConformanceState.PASSED:
            raise ValueError(f"live source conformance is {state.value}")
        query = ScoutQuery(
            objective=objective, queries=(objective,), maximum_sources=1, maximum_snapshots=1,
            maximum_bytes=config.maximum_bytes, maximum_duration_seconds=config.timeout_seconds,
            allowed_domains=config.allowed_domains, blocked_domains=config.blocked_domains,
            autonomy_level=AutonomyLevel.OBSERVE, metadata={"live_acquisition": True},
        )
        snapshot = await adapter.fetch(SearchHit(
            source_id=config.source_id, url=url, title=title or url, snippet="", rank=1, query=objective,
        ), query)
        stored = self.opportunity_engine.record_snapshot(snapshot)
        claims = []
        for claim in await self.extractor.extract(stored, query):
            claims.append(self.opportunity_engine.record_claim(claim))
        return {
            "snapshot": stored, "claims": tuple(claims), "conformance_state": state.value,
            "adapter_id": adapter_id, "live_network": True,
        }


_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+")


class AdaptiveSourceDiscovery:
    """Finds candidate sources from observed content; activation remains an operator decision."""

    def __init__(self, opportunity_store: SQLiteOpportunityStore, engine: WebIntelligenceEngine) -> None:
        self.opportunity_store = opportunity_store
        self.engine = engine

    def discover(self, *, minimum_mentions: int = 1, maximum_candidates: int = 50) -> tuple[SourceDiscoveryCandidate, ...]:
        known = {domain.casefold() for config in self.engine.store.configurations() for domain in config.allowed_domains}
        domain_to_snapshots: dict[str, set[str]] = {}
        domain_to_url: dict[str, str] = {}
        for snapshot in self.opportunity_store.list_snapshots(limit=2000):
            urls = set(_URL_RE.findall(snapshot.content_text))
            for url in urls:
                parsed = urlparse(url.rstrip(".,;"))
                host = (parsed.hostname or "").casefold()
                if parsed.scheme not in {"http", "https"} or not host or host in known:
                    continue
                domain_to_snapshots.setdefault(host, set()).add(snapshot.snapshot_id)
                domain_to_url.setdefault(host, f"{parsed.scheme}://{host}")
        proposed = []
        for domain, snapshots in sorted(domain_to_snapshots.items(), key=lambda item: (-len(item[1]), item[0])):
            if len(snapshots) < minimum_mentions:
                continue
            risk = "medium" if any(token in domain for token in ("social", "login", "account")) else "low"
            candidate = self.engine.propose_source(SourceDiscoveryCandidate(
                discovered_url=domain_to_url[domain], canonical_domain=domain,
                discovered_from_snapshot_ids=tuple(sorted(snapshots)),
                capabilities=("fetch", "crawl"),
                reason=f"Observed in {len(snapshots)} provenance-bound snapshot(s).",
                confidence=min(0.95, 0.45 + len(snapshots) * 0.1), risk=risk,
                metadata={"adaptive_discovery": True, "mention_count": len(snapshots)},
            ))
            proposed.append(candidate)
            if len(proposed) >= maximum_candidates:
                break
        return tuple(proposed)
