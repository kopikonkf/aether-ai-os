from __future__ import annotations

from dataclasses import replace

import pytest

from aether.contracts import (
    AutonomyLevel, ExperimentMandate, ExperimentStep, ExperimentStepKind,
    MandateStatus, OpportunityCandidate, OpportunityScore, OpportunityStatus,
    PortfolioDecision, PortfolioDecisionType, ReversibleExperimentPlan,
    mandate_hash,
)
from aether.experiments import ReversibleExperimentEngine, SQLiteExperimentStore
from aether.opportunities import SQLiteOpportunityStore
from aether_gateway.experiments import ReversibleExperimentRunner


def lineage(tmp_path):
    os = SQLiteOpportunityStore(tmp_path / "opportunities.sqlite3")
    c = OpportunityCandidate(
        title="Test", problem_statement="Problem", beneficiary="User", value_proposition="Value",
        revenue_hypothesis="Hypothesis", category="test", claim_ids=("a", "b"), supporting_source_ids=("s1", "s2"),
        contradicting_claim_ids=(), assumptions=("a",), score=OpportunityScore(10,.8,.8,.9,.9,.1,.1,.1,.1,5),
        expected_upside_usd=20, probability_success=.6, estimated_cost_usd=2, estimated_duration_hours=1,
        risk="low", status=OpportunityStatus.SELECTED, candidate_hash="candidate", created_at="2026-07-28T00:00:00Z",
    ); os.add_candidate(c)
    os.add_decision(PortfolioDecision(c.candidate_id, PortfolioDecisionType.SELECT, "founder", "Approve reversible prototype.", 10, decided_at="2026-07-28T00:00:00Z"))
    m = ExperimentMandate(
        candidate_id=c.candidate_id, principal="founder", autonomy_level=AutonomyLevel.SANDBOX_EXPERIMENT,
        allowed_capabilities=("prototype.build","prototype.verify","preview.private","demand.measure"),
        forbidden_capabilities=("credential-export",), maximum_cost_usd=10, maximum_external_actions=0,
        maximum_duration_seconds=3600, reversible_only=True, expires_at="2099-01-01T00:00:00Z", reason="Bounded reversible validation.",
        status=MandateStatus.ACTIVE, issued_at="2026-07-28T00:00:00Z",
    ); m=replace(m, mandate_hash=mandate_hash(m)); os.add_mandate(m)
    es=SQLiteExperimentStore(tmp_path / "experiments.sqlite3"); engine=ReversibleExperimentEngine(es, os)
    return c,m,es,engine


@pytest.mark.asyncio
async def test_runner_builds_validates_and_deploys_private_preview(tmp_path):
    c,m,store,engine=lineage(tmp_path)
    plan=engine.create_plan(ReversibleExperimentPlan(
        candidate_id=c.candidate_id, mandate_id=m.mandate_id, objective="Private validation", hypothesis="CTA is understandable",
        success_metrics=("page valid",), stop_conditions=("validation fails",), maximum_cost_usd=5, maximum_duration_seconds=300,
        steps=(
            ExperimentStep("Build",ExperimentStepKind.WRITE_ARTIFACT,"prototype.build",{"files":{"index.html":"<!doctype html><title>Proof</title><h1>Proof</h1>","app.js":"console.log('ok')"}},1),
            ExperimentStep("Verify",ExperimentStepKind.VERIFY_ARTIFACT,"prototype.verify",{"required_files":["index.html","app.js"],"contains":{"index.html":["<title>Proof</title>"]}},1),
            ExperimentStep("Preview",ExperimentStepKind.PRIVATE_PREVIEW,"preview.private",{"index_file":"index.html","ttl_seconds":3600},0),
            ExperimentStep("Measure",ExperimentStepKind.MEASURE_DEMAND,"demand.measure",{},0),
        ),
    ))
    runner=ReversibleExperimentRunner(tmp_path / "runtime",engine)
    run,token=await runner.run(plan.plan_id)
    assert run.status.value == "preview-ready"
    assert token and run.preview_id
    assert runner.resolve_preview_file(run.preview_id, token).read_text().find("Proof") >= 0
    with pytest.raises(Exception, match="invalid private preview token"):
        runner.resolve_preview_file(run.preview_id, "wrong")
    again,again_token=await runner.run(plan.plan_id)
    assert again.run_id == run.run_id and again_token is None
    assert store.status()["experiment_artifacts"] == 2

@pytest.mark.asyncio
async def test_runner_enforces_artifact_file_and_elapsed_duration_budgets(tmp_path, monkeypatch):
    c,m,store,engine=lineage(tmp_path)
    file_limited=engine.create_plan(ReversibleExperimentPlan(
        candidate_id=c.candidate_id, mandate_id=m.mandate_id, objective="File bounded prototype",
        hypothesis="One file is sufficient", success_metrics=("bounded",), stop_conditions=("file budget",),
        maximum_cost_usd=1, maximum_duration_seconds=300, maximum_artifact_files=1,
        steps=(ExperimentStep(
            "Build", ExperimentStepKind.WRITE_ARTIFACT, "prototype.build",
            {"files":{"index.html":"<h1>one</h1>","app.js":"console.log('two')"}}, 0,
        ),),
    ))
    runner=ReversibleExperimentRunner(tmp_path / "runtime-files", engine)
    run,_=await runner.run(file_limited.plan_id)
    assert run.status.value == "failed"
    assert "artifact file budget exceeded" in (run.stop_reason or "")
    assert run.metadata["artifact_files"] == 1

    duration_limited=engine.create_plan(ReversibleExperimentPlan(
        candidate_id=c.candidate_id, mandate_id=m.mandate_id, objective="Duration bounded prototype",
        hypothesis="Execution remains bounded", success_metrics=("bounded",), stop_conditions=("duration budget",),
        maximum_cost_usd=1, maximum_duration_seconds=1,
        steps=(ExperimentStep(
            "Build", ExperimentStepKind.WRITE_ARTIFACT, "prototype.build",
            {"files":{"index.html":"<h1>late</h1>"}}, 0,
        ),),
    ))
    import aether_gateway.experiments.runner as runner_module
    ticks=iter((0.0, 2.0, 2.0, 2.0))
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: next(ticks, 2.0))
    delayed_runner=ReversibleExperimentRunner(tmp_path / "runtime-duration", engine)
    delayed,_=await delayed_runner.run(duration_limited.plan_id)
    assert delayed.status.value == "failed"
    assert "experiment duration budget exceeded" in (delayed.stop_reason or "")
    assert delayed.metadata["duration_seconds"] >= 2
