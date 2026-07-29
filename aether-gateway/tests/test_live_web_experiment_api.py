from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_live_web_and_reversible_experiment_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "experiment-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "experiment-secret"}

    with TestClient(server.app) as client:
        assert client.get("/api/experiments/console").status_code == 401
        initial = client.get("/api/experiments/console", headers=headers)
        assert initial.status_code == 200
        assert initial.json()["authority"]["synthetic_is_not_measured"] is True

        configured = client.post("/api/web-intelligence/configurations", headers=headers, json={
            "adapter_id": "source.adapter.public-http",
            "source_id": "source.web.public-http",
            "endpoint": "https://example.com",
            "allowed_domains": ["example.com"],
            "enabled": False,
            "maximum_pages": 1,
            "maximum_depth": 0,
            "maximum_bytes": 100000,
            "timeout_seconds": 10,
        })
        assert configured.status_code == 200, configured.text
        assert configured.json()["credential_handle_present"] is False

        conformance = client.post(
            "/api/web-intelligence/sources/source.adapter.public-http/conform",
            headers=headers, json={"ttl_seconds": 3600},
        )
        assert conformance.status_code == 200, conformance.text
        assert conformance.json()["state"] == "failed"

        scout = client.post("/api/opportunity-intelligence/scout-runs", headers=headers, json={
            "objective": "AI business automation opportunity",
            "queries": ["automation agent"],
            "source_kinds": ["catalog"],
            "maximum_sources": 5,
            "maximum_snapshots": 10,
            "maximum_bytes": 100000,
            "maximum_duration_seconds": 30,
            "autonomy_level": "observe",
        })
        assert scout.status_code == 200, scout.text
        claim_ids = scout.json()["claim_ids"]
        candidate = client.post("/api/opportunity-intelligence/candidates", headers=headers, json={
            "title": "Private workflow prototype",
            "problem_statement": "Operators repeat a costly workflow.",
            "beneficiary": "Small service operators",
            "value_proposition": "A private prototype tests whether the workflow can be simplified.",
            "revenue_hypothesis": "Measured demand may support a paid implementation.",
            "category": "operations-automation",
            "claim_ids": claim_ids[:4],
            "assumptions": ["A synthetic workflow can represent the bottleneck."],
            "expected_upside_usd": 500,
            "probability_success": 0.6,
            "estimated_cost_usd": 20,
            "estimated_duration_hours": 2,
            "risk": "low",
            "strategic_alignment": 0.9,
            "reversibility": 0.95,
            "time_to_validation": 0.9,
            "legal_risk_penalty": 0.05,
            "platform_dependency_penalty": 0.05,
            "saturation_penalty": 0.1,
        })
        assert candidate.status_code == 200, candidate.text
        candidate_id = candidate.json()["candidate_id"]
        decision = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/decision", headers=headers, json={
            "decision": "select",
            "reason": "Independent evidence supports one private reversible experiment.",
            "allocated_budget_usd": 20,
        })
        assert decision.status_code == 200, decision.text
        mandate = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/mandates", headers=headers, json={
            "autonomy_level": "sandbox-experiment",
            "allowed_capabilities": ["prototype.build", "prototype.verify", "preview.private", "demand.measure"],
            "maximum_cost_usd": 15,
            "maximum_external_actions": 0,
            "maximum_duration_seconds": 3600,
            "reason": "Build, verify, and privately preview one reversible prototype.",
        })
        assert mandate.status_code == 200, mandate.text
        mandate_id = mandate.json()["mandate_id"]

        plan = client.post("/api/experiments/plans", headers=headers, json={
            "candidate_id": candidate_id,
            "mandate_id": mandate_id,
            "objective": "Test a private landing page prototype.",
            "hypothesis": "A clear value proposition creates measurable interest.",
            "success_metrics": ["prototype passes validation", "measurement surface is ready"],
            "stop_conditions": ["validation fails", "budget exhausted"],
            "maximum_cost_usd": 5,
            "maximum_duration_seconds": 300,
            "steps": [
                {"name": "Build", "kind": "write-artifact", "capability": "prototype.build", "estimated_cost_usd": 1,
                 "payload": {"files": {"index.html": "<!doctype html><title>Aether Proof</title><h1>Aether Proof</h1><button>Join</button>", "app.js": "console.log('private')"}}},
                {"name": "Verify", "kind": "verify-artifact", "capability": "prototype.verify", "estimated_cost_usd": 1,
                 "payload": {"required_files": ["index.html", "app.js"], "contains": {"index.html": ["Aether Proof", "Join"]}}},
                {"name": "Preview", "kind": "private-preview", "capability": "preview.private", "payload": {"index_file": "index.html", "ttl_seconds": 3600}},
                {"name": "Measure", "kind": "measure-demand", "capability": "demand.measure", "payload": {}},
            ],
        })
        assert plan.status_code == 200, plan.text
        run = client.post(f"/api/experiments/plans/{plan.json()['plan_id']}/run", headers=headers)
        assert run.status_code == 200, run.text
        run_data = run.json()
        assert run_data["status"] == "preview-ready"
        preview = run_data["private_preview"]
        page = client.get(preview["url"])
        assert page.status_code == 200
        assert "Aether Proof" in page.text

        synthetic = client.post(f"/api/experiments/runs/{run_data['run_id']}/demand-signals", headers=headers, json={
            "kind": "synthetic", "state": "measured", "quantity": 10,
            "unit": "views", "source": "simulation", "external_reference": "synthetic://views",
        })
        assert synthetic.status_code == 409
        measured = client.post(f"/api/experiments/runs/{run_data['run_id']}/demand-signals", headers=headers, json={
            "kind": "page-view", "state": "measured", "quantity": 3,
            "unit": "views", "source": "private-preview-analytics",
            "external_reference": "analytics://private-preview/session-1",
        })
        assert measured.status_code == 200, measured.text
        assert measured.json()["state"] == "measured"

        console = client.get("/api/experiments/console", headers=headers).json()
        assert console["experiments"]["status"]["experiment_runs"] == 1
        assert console["experiments"]["status"]["demand_signals"] == 1
        assert console["web"]["status"]["source_conformance_receipts"] == 1
