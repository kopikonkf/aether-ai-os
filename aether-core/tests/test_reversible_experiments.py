from __future__ import annotations

from dataclasses import replace

import pytest

from aether.contracts import (
    AutonomyLevel, ClaimStance, ContentSnapshot, DemandEvidenceState, DemandSignal,
    DemandSignalKind, EvidenceStrength, ExperimentBlocked, ExperimentMandate,
    ExperimentRunReceipt, ExperimentStatus, ExperimentStep, ExperimentStepKind,
    ExtractedClaim, MandateStatus, OpportunityCandidate, OpportunityScore,
    OpportunityStatus, PortfolioDecision, PortfolioDecisionType, ReversibleExperimentPlan,
    experiment_mandate_payload, mandate_hash,
)
from aether.experiments import ReversibleExperimentEngine, SQLiteExperimentStore
from aether.opportunities import SQLiteOpportunityStore


def setup_lineage(tmp_path, *, autonomy=AutonomyLevel.SANDBOX_EXPERIMENT, external_actions=0):
    opportunities = SQLiteOpportunityStore(tmp_path / "opportunities.sqlite3")
    score = OpportunityScore(100, .8, .9, .9, .8, .1, .05, .05, .1, 50)
    candidate = OpportunityCandidate(
        title="Private validation prototype", problem_statement="Users need a faster workflow.", beneficiary="Operators",
        value_proposition="Private prototype validates demand.", revenue_hypothesis="Users may pay after validation.",
        category="operations", claim_ids=("claim-a", "claim-b"), supporting_source_ids=("source-a", "source-b"),
        contradicting_claim_ids=(), assumptions=("Demand persists",), score=score,
        expected_upside_usd=200, probability_success=.6, estimated_cost_usd=10, estimated_duration_hours=2,
        risk="low", status=OpportunityStatus.SELECTED, candidate_hash="candidate-hash", created_at="2026-07-28T00:00:00Z",
    )
    opportunities.add_candidate(candidate)
    opportunities.add_decision(PortfolioDecision(
        candidate_id=candidate.candidate_id, decision=PortfolioDecisionType.SELECT, principal="founder",
        reason="Evidence supports a reversible experiment.", allocated_budget_usd=20,
        decided_at="2026-07-28T00:00:00Z",
    ))
    mandate = ExperimentMandate(
        candidate_id=candidate.candidate_id, principal="founder", autonomy_level=autonomy,
        allowed_capabilities=("prototype.build", "prototype.verify", "preview.private", "demand.measure", "external.publish"),
        forbidden_capabilities=("credential-export", "self-approval"), maximum_cost_usd=20,
        maximum_external_actions=external_actions, maximum_duration_seconds=3600, reversible_only=True,
        expires_at="2099-07-28T00:00:00Z", reason="Bounded reversible validation.", status=MandateStatus.ACTIVE,
        issued_at="2026-07-28T00:00:00Z",
    )
    mandate = replace(mandate, mandate_hash=mandate_hash(mandate))
    opportunities.add_mandate(mandate)
    store = SQLiteExperimentStore(tmp_path / "experiments.sqlite3")
    return ReversibleExperimentEngine(store, opportunities), store, candidate, mandate


def make_plan(candidate, mandate, *, external=False):
    steps = [
        ExperimentStep("Build", ExperimentStepKind.WRITE_ARTIFACT, "prototype.build", {"files": {"index.html": "<h1>Test</h1>"}}, estimated_cost_usd=1),
        ExperimentStep("Verify", ExperimentStepKind.VERIFY_ARTIFACT, "prototype.verify", {"required_files": ["index.html"]}, estimated_cost_usd=1),
    ]
    if external:
        steps.append(ExperimentStep("Publish", ExperimentStepKind.EXTERNAL_ACTION, "external.publish", {"action_summary": "Publish preview"}, external_actions=1))
    return ReversibleExperimentPlan(
        candidate_id=candidate.candidate_id, mandate_id=mandate.mandate_id,
        objective="Test demand with a private reversible prototype.", hypothesis="A focused prototype improves workflow comprehension.",
        success_metrics=("prototype validates",), stop_conditions=("budget exhausted",), steps=tuple(steps),
        maximum_cost_usd=5, maximum_duration_seconds=300,
    )


def test_plan_must_fit_exact_mandate_and_is_idempotent(tmp_path):
    engine, store, candidate, mandate = setup_lineage(tmp_path)
    plan = engine.create_plan(make_plan(candidate, mandate))
    duplicate = engine.create_plan(make_plan(candidate, mandate))
    assert plan.plan_hash == duplicate.plan_hash
    assert store.status()["experiment_plans"] == 1
    expensive = replace(make_plan(candidate, mandate), maximum_cost_usd=30)
    with pytest.raises(ExperimentBlocked, match="exceeds mandate"):
        engine.create_plan(expensive)


def test_external_action_requires_bounded_external_mandate(tmp_path):
    engine, _, candidate, mandate = setup_lineage(tmp_path)
    with pytest.raises(ExperimentBlocked, match="bounded-external"):
        engine.create_plan(make_plan(candidate, mandate, external=True))


def test_synthetic_is_not_measured_and_measured_requires_external_reference(tmp_path):
    engine, store, candidate, mandate = setup_lineage(tmp_path)
    plan = engine.create_plan(make_plan(candidate, mandate))
    run = engine.record_run(ExperimentRunReceipt(
        plan_id=plan.plan_id, candidate_id=candidate.candidate_id, mandate_id=mandate.mandate_id,
        status=ExperimentStatus.COMPLETED, workspace_path="/tmp/work", started_at="2026-07-28T00:00:00Z",
        completed_at="2026-07-28T00:01:00Z", cost_usd=2, step_receipt_ids=(), artifact_ids=(),
    ))
    with pytest.raises(ExperimentBlocked, match="synthetic"):
        engine.record_demand_signal(DemandSignal(
            run_id=run.run_id, kind=DemandSignalKind.SYNTHETIC, state=DemandEvidenceState.MEASURED,
            quantity=10, unit="views", measured_at="2026-07-28T00:02:00Z", source="simulation",
            external_reference="synthetic://views",
        ))
    with pytest.raises(ExperimentBlocked, match="external reference"):
        engine.record_demand_signal(DemandSignal(
            run_id=run.run_id, kind=DemandSignalKind.PAGE_VIEW, state=DemandEvidenceState.MEASURED,
            quantity=10, unit="views", measured_at="2026-07-28T00:02:00Z", source="preview-analytics",
        ))
    measured = engine.record_demand_signal(DemandSignal(
        run_id=run.run_id, kind=DemandSignalKind.PAGE_VIEW, state=DemandEvidenceState.MEASURED,
        quantity=10, unit="views", measured_at="2026-07-28T00:02:00Z", source="preview-analytics",
        external_reference="analytics://preview/session-1",
    ))
    assert measured.signal_hash
    assert store.signals(run.run_id)[0].state == DemandEvidenceState.MEASURED
