"""Governed live-source configuration, conformance receipts, freshness, and discovery proposals."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlparse

from aether.contracts.opportunities import ContentSnapshot
from aether.contracts.web_intelligence import (
    EvidenceFreshnessPolicy, EvidenceFreshnessRecord, FreshnessState,
    LiveSourceConfiguration, SourceConformanceReceipt, SourceConformanceState,
    SourceDiscoveryCandidate, SourceDiscoveryState, WebIntelligenceBlocked,
    live_source_configuration_hash, source_conformance_receipt_hash,
    source_discovery_candidate_hash, canonical_web_hash,
)
from aether.utils.time import utc_now
from aether.web_intelligence.store import SQLiteWebIntelligenceStore


class WebIntelligenceGovernor:
    def __init__(self, trusted_principals: tuple[str, ...] = ("founder", "operator")) -> None:
        self.trusted_principals = tuple(value.casefold() for value in trusted_principals)

    def require_trusted(self, principal: str) -> None:
        if principal.casefold() not in self.trusted_principals:
            raise WebIntelligenceBlocked(("trusted principal required",))

    def validate_configuration(self, item: LiveSourceConfiguration) -> tuple[str, ...]:
        blockers: list[str] = []
        if not item.adapter_id or not item.source_id:
            blockers.append("adapter_id and source_id are required")
        parsed = urlparse(item.endpoint)
        if item.endpoint and parsed.scheme not in {"http", "https", "local"}:
            blockers.append("endpoint scheme must be http, https, or local")
        if not item.allowed_domains and parsed.scheme in {"http", "https"}:
            blockers.append("live network configuration requires an explicit domain allowlist")
        if item.maximum_pages < 1 or item.maximum_depth < 0 or item.maximum_bytes < 1024:
            blockers.append("crawl resource limits are invalid")
        if item.timeout_seconds < 1:
            blockers.append("timeout_seconds must be positive")
        return tuple(blockers)


class WebIntelligenceEngine:
    def __init__(self, store: SQLiteWebIntelligenceStore, *, governor: WebIntelligenceGovernor | None = None) -> None:
        self.store = store
        self.governor = governor or WebIntelligenceGovernor()

    def configure_source(self, item: LiveSourceConfiguration, *, principal: str) -> LiveSourceConfiguration:
        self.governor.require_trusted(principal)
        blockers = self.governor.validate_configuration(item)
        if blockers:
            raise WebIntelligenceBlocked(blockers)
        stamped = replace(
            item, configured_by=principal, configured_at=item.configured_at or utc_now(),
            configuration_hash=live_source_configuration_hash(replace(item, configuration_hash="")),
        )
        return self.store.add_configuration(stamped)

    def record_conformance(self, item: SourceConformanceReceipt) -> SourceConformanceReceipt:
        config = self.store.latest_configuration(item.adapter_id)
        blockers: list[str] = []
        if config is None:
            blockers.append("source configuration is missing")
        elif config.configuration_hash != item.configuration_hash:
            blockers.append("conformance receipt does not match latest configuration")
        if not item.checks:
            blockers.append("conformance receipt requires checks")
        if item.state == SourceConformanceState.PASSED and not all(check.passed for check in item.checks):
            blockers.append("passed conformance requires all checks to pass")
        if blockers:
            raise WebIntelligenceBlocked(blockers)
        stamped = replace(item, receipt_hash=source_conformance_receipt_hash(replace(item, receipt_hash="")))
        return self.store.add_conformance(stamped)

    def effective_conformance(self, adapter_id: str, *, manifest_hash: str, now: str | None = None) -> SourceConformanceState:
        receipt = self.store.latest_conformance(adapter_id)
        config = self.store.latest_configuration(adapter_id)
        if receipt is None or config is None:
            return SourceConformanceState.MISSING
        if receipt.configuration_hash != config.configuration_hash or receipt.manifest_hash != manifest_hash:
            return SourceConformanceState.STALE
        current = datetime.fromisoformat((now or utc_now()).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(receipt.expires_at.replace("Z", "+00:00"))
        if current >= expires:
            return SourceConformanceState.EXPIRED
        return receipt.state

    def evaluate_freshness(
        self, snapshot: ContentSnapshot, policy: EvidenceFreshnessPolicy, *, evaluated_at: str | None = None,
    ) -> EvidenceFreshnessRecord:
        policy.validate()
        now_text = evaluated_at or utc_now()
        now = datetime.fromisoformat(now_text.replace("Z", "+00:00"))
        retrieved = datetime.fromisoformat(snapshot.retrieved_at.replace("Z", "+00:00"))
        age = max(0, int((now - retrieved).total_seconds()))
        if age <= policy.fresh_for_seconds:
            state = FreshnessState.FRESH
        elif age <= policy.aging_for_seconds:
            state = FreshnessState.AGING
        else:
            state = FreshnessState.STALE
        return self.store.add_freshness(EvidenceFreshnessRecord(
            snapshot_id=snapshot.snapshot_id, source_id=snapshot.source_id,
            canonical_url=snapshot.canonical_url, retrieved_at=snapshot.retrieved_at,
            evaluated_at=now_text, age_seconds=age, state=state,
            refresh_required=state in {FreshnessState.AGING, FreshnessState.STALE},
            content_hash=snapshot.content_hash,
        ))

    def propose_source(self, item: SourceDiscoveryCandidate) -> SourceDiscoveryCandidate:
        blockers: list[str] = []
        parsed = urlparse(item.discovered_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            blockers.append("discovered source requires an http(s) URL")
        if not item.discovered_from_snapshot_ids:
            blockers.append("discovered source requires provenance snapshots")
        if not 0 <= item.confidence <= 1:
            blockers.append("confidence must be between 0 and 1")
        if blockers:
            raise WebIntelligenceBlocked(blockers)
        stamped = replace(
            item, canonical_domain=(parsed.hostname or "").casefold(), proposed_at=item.proposed_at or utc_now(),
            state=SourceDiscoveryState.PROPOSED,
        )
        stamped = replace(stamped, candidate_hash=source_discovery_candidate_hash(stamped))
        return self.store.add_discovery(stamped)

    def decide_source(self, candidate_id: str, *, state: SourceDiscoveryState, principal: str, reason: str) -> SourceDiscoveryCandidate:
        self.governor.require_trusted(principal)
        if state not in {SourceDiscoveryState.ACCEPTED, SourceDiscoveryState.REJECTED}:
            raise WebIntelligenceBlocked(("terminal source discovery decision required",))
        existing = self.store.get_discovery(candidate_id)
        if existing.state != SourceDiscoveryState.PROPOSED:
            raise WebIntelligenceBlocked(("source discovery candidate already decided",))
        # Append a decision record with the same provenance but a distinct hash lineage.
        decided = replace(
            existing, candidate_id=f"{existing.candidate_id}:{state.value}", state=state,
            decided_by=principal, decided_at=utc_now(), decision_reason=reason,
            candidate_hash=canonical_web_hash({"parent": existing.candidate_hash, "state": state.value, "principal": principal}),
        )
        return self.store.add_discovery(decided)
