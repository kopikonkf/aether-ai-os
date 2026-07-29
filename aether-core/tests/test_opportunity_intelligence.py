from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from aether.contracts import (
    AutonomyLevel, ClaimStance, ContentSnapshot, EvidenceStrength, ExperimentMandate,
    ExtractedClaim, OpportunityBlocked, OpportunityStatus, PortfolioDecisionConflict,
    PortfolioDecisionType, PortfolioPolicy, SourceAdapterManifest, SourceCapability, SourceKind,
    mandate_hash, source_manifest_hash,
)
from aether.opportunities import OpportunityIntelligenceEngine, SQLiteOpportunityStore


def make_engine(tmp_path):
    store = SQLiteOpportunityStore(tmp_path / "opportunities.sqlite3")
    return OpportunityIntelligenceEngine(store), store


def add_source(engine, suffix):
    item = SourceAdapterManifest(
        source_id=f"source-{suffix}", adapter_id=f"adapter-{suffix}", name=f"Source {suffix}",
        kind=SourceKind.CATALOG, capabilities=(SourceCapability.SEARCH, SourceCapability.FETCH),
        forbidden_capabilities=("credential-export",),
    )
    return engine.register_source(item)


def add_claim(engine, suffix, *, stance=ClaimStance.SUPPORTS, subject="workflow automation"):
    source = add_source(engine, suffix)
    text = f"Independent operators report recurring demand for {subject} and measurable time savings in source {suffix}."
    snapshot = engine.record_snapshot(ContentSnapshot(
        source_id=source.source_id, adapter_id=source.adapter_id,
        canonical_url=f"https://example.com/{suffix}", title=f"Evidence {suffix}", content_text=text,
        content_type="text/plain", retrieved_at="2026-07-28T00:00:00Z",
        content_hash=__import__("hashlib").sha256(text.encode()).hexdigest(),
        source_reference=f"https://example.com/{suffix}", policy_fingerprint=source.manifest_hash,
    ))
    return engine.record_claim(ExtractedClaim(
        snapshot_id=snapshot.snapshot_id, source_id=source.source_id, statement=text,
        stance=stance, subject=subject, confidence=0.8, evidence_strength=EvidenceStrength.STRONG,
        observed_at="2026-07-28T00:00:00Z", external_reference=snapshot.canonical_url,
        extractor_id="test-extractor",
    ))


def synthesize(engine, claims, **overrides):
    values = dict(
        title="Automate repetitive operator workflow", problem_statement="Small operators repeat an expensive manual workflow.",
        beneficiary="Small service operators", value_proposition="Deliver a reversible automation proof.",
        revenue_hypothesis="Operators pay for verified time savings.", category="operations-automation",
        claim_ids=[item.claim_id for item in claims], assumptions=["The workflow remains repetitive."],
        expected_upside_usd=1000.0, probability_success=0.6, estimated_cost_usd=100.0,
        estimated_duration_hours=8.0, risk="low", strategic_alignment=0.9, reversibility=0.9,
        time_to_validation=0.8, legal_risk_penalty=0.05, platform_dependency_penalty=0.1,
        saturation_penalty=0.15, strategy_tags=("business-experimentation",),
    )
    values.update(overrides)
    return engine.synthesize_candidate(**values)


def test_source_manifest_and_evidence_ledger_are_append_only(tmp_path):
    engine, store = make_engine(tmp_path)
    source = add_source(engine, "one")
    claim = add_claim(engine, "two")
    assert source.manifest_hash == source_manifest_hash(replace(source, manifest_hash=""))
    assert claim.claim_hash
    with sqlite3.connect(store.path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE content_snapshots SET content_hash='changed'")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("DELETE FROM extracted_claims")


def test_two_independent_sources_make_candidate_portfolio_ready(tmp_path):
    engine, _ = make_engine(tmp_path)
    candidate = synthesize(engine, [add_claim(engine, "a"), add_claim(engine, "b")])
    assert candidate.status == OpportunityStatus.PORTFOLIO_READY
    assert candidate.blockers == ()
    assert len(candidate.supporting_source_ids) == 2
    assert candidate.score.expected_net_value_usd == 500.0
    assert candidate.score.utility_score > 0


def test_contradiction_blocks_candidate_without_starving_observation(tmp_path):
    engine, _ = make_engine(tmp_path)
    claims = [add_claim(engine, "a"), add_claim(engine, "b"), add_claim(engine, "c", stance=ClaimStance.CONTRADICTS)]
    candidate = synthesize(engine, claims)
    assert candidate.status == OpportunityStatus.EVIDENCE_REQUIRED
    assert candidate.contradicting_claim_ids
    assert "unresolved contradiction" in " ".join(candidate.blockers)
    # The evidence remains in the ledger; it is not censored or discarded.
    assert len(engine.store.claims(subject="workflow automation")) == 3


def test_portfolio_selection_enforces_budget_risk_and_category_diversity(tmp_path):
    engine, _ = make_engine(tmp_path)
    claims = [add_claim(engine, "a"), add_claim(engine, "b")]
    first = synthesize(engine, claims, title="Operations A", category="operations", estimated_cost_usd=30.0)
    second = synthesize(engine, claims, title="Operations B", category="operations", estimated_cost_usd=20.0)
    third = synthesize(engine, claims, title="Sales A", category="sales", estimated_cost_usd=25.0)
    selection = engine.select_portfolio(
        [first, second, third],
        PortfolioPolicy(maximum_selected_candidates=2, maximum_total_experiment_budget_usd=60.0, maximum_single_category_fraction=0.5),
    )
    assert len(selection.candidate_ids) == 2
    selected_categories = {engine.store.get_candidate(item).category for item in selection.candidate_ids}
    assert selected_categories == {"operations", "sales"}
    assert selection.allocated_budget_usd <= 60.0


def test_trusted_selection_and_progressive_autonomy_mandate(tmp_path):
    engine, store = make_engine(tmp_path)
    candidate = synthesize(engine, [add_claim(engine, "a"), add_claim(engine, "b")], estimated_cost_usd=25.0)
    with pytest.raises(OpportunityBlocked, match="trusted"):
        engine.decide(candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="model", reason="Model selects this experiment because it looks useful.", allocated_budget_usd=25.0)
    decision = engine.decide(candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="founder", reason="Evidence is independent and the reversible experiment is bounded.", allocated_budget_usd=25.0)
    assert decision.decision == PortfolioDecisionType.SELECT
    with pytest.raises(OpportunityBlocked, match="exceeds"):
        engine.issue_mandate(
            candidate.candidate_id, principal="founder", autonomy_level=AutonomyLevel.SANDBOX_EXPERIMENT,
            allowed_capabilities=("prototype.build",), maximum_cost_usd=30.0, maximum_external_actions=0,
            maximum_duration_seconds=3600, reason="Run one reversible prototype experiment within the selected allocation.",
        )
    mandate = engine.issue_mandate(
        candidate.candidate_id, principal="founder", autonomy_level=AutonomyLevel.SANDBOX_EXPERIMENT,
        allowed_capabilities=("prototype.build", "prototype.verify"), maximum_cost_usd=20.0,
        maximum_external_actions=0, maximum_duration_seconds=3600,
        reason="Run one reversible prototype experiment within the selected allocation.",
    )
    assert mandate.mandate_hash == mandate_hash(replace(mandate, mandate_hash=""))
    assert "credential-export" in mandate.forbidden_capabilities
    assert store.mandates(candidate.candidate_id)[0].mandate_id == mandate.mandate_id
    with pytest.raises(PortfolioDecisionConflict):
        engine.decide(candidate.candidate_id, decision=PortfolioDecisionType.REJECT, principal="founder", reason="Attempt to reverse an immutable terminal portfolio decision.")


def test_high_consequence_cannot_be_reusable_mandate(tmp_path):
    engine, _ = make_engine(tmp_path)
    candidate = synthesize(engine, [add_claim(engine, "a"), add_claim(engine, "b")], estimated_cost_usd=5.0)
    engine.decide(candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="founder", reason="Approve a small evidence-backed experiment.", allocated_budget_usd=5.0)
    with pytest.raises(OpportunityBlocked, match="high-consequence"):
        engine.issue_mandate(
            candidate.candidate_id, principal="founder", autonomy_level=AutonomyLevel.HIGH_CONSEQUENCE,
            allowed_capabilities=("contract.sign",), maximum_cost_usd=1.0, maximum_external_actions=1,
            maximum_duration_seconds=60, reason="Attempt to grant reusable high-consequence authority.",
        )
