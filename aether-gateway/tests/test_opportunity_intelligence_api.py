from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_opportunity_intelligence_api_scans_scores_mandates_and_converts(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "opportunity-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "opportunity-secret"}

    with TestClient(server.app) as client:
        assert client.get("/api/opportunity-intelligence/console").status_code == 401
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
        receipt = scout.json()
        assert receipt["status"] == "completed"
        assert len(receipt["source_ids"]) == 2
        assert len(receipt["claim_ids"]) >= 2

        candidate = client.post("/api/opportunity-intelligence/candidates", headers=headers, json={
            "title": "Bounded AI workflow automation proof",
            "problem_statement": "Small operators repeat costly workflows and lack safe agent integration.",
            "beneficiary": "Small service operators",
            "value_proposition": "Build and verify one reversible automation proof before external shipping.",
            "revenue_hypothesis": "An operator pays after measured time savings are independently verified.",
            "category": "operations-automation",
            "claim_ids": receipt["claim_ids"][:4],
            "assumptions": ["The repeated workflow can be represented in a synthetic test environment."],
            "expected_upside_usd": 1000,
            "probability_success": 0.6,
            "estimated_cost_usd": 50,
            "estimated_duration_hours": 8,
            "risk": "low",
            "strategic_alignment": 0.9,
            "reversibility": 0.95,
            "time_to_validation": 0.8,
            "legal_risk_penalty": 0.05,
            "platform_dependency_penalty": 0.05,
            "saturation_penalty": 0.15,
            "strategy_tags": ["business-experimentation", "human-value"],
        })
        assert candidate.status_code == 200, candidate.text
        candidate_data = candidate.json()
        assert candidate_data["status"] == "portfolio-ready"
        candidate_id = candidate_data["candidate_id"]

        scored = client.post("/api/opportunity-intelligence/portfolio/score", headers=headers, json={
            "maximum_selected_candidates": 3,
            "maximum_total_experiment_budget_usd": 100,
            "minimum_independent_sources": 2,
        })
        assert scored.status_code == 200, scored.text
        assert candidate_id in scored.json()["candidate_ids"]

        denied = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/mandates", headers=headers, json={
            "autonomy_level": "sandbox-experiment",
            "allowed_capabilities": ["prototype.build"],
            "maximum_cost_usd": 10,
            "maximum_external_actions": 0,
            "maximum_duration_seconds": 3600,
            "reason": "Try to issue mandate before trusted portfolio selection.",
        })
        assert denied.status_code == 400

        decision = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/decision", headers=headers, json={
            "decision": "select",
            "reason": "Independent evidence supports a reversible experiment inside a small budget.",
            "allocated_budget_usd": 50,
        })
        assert decision.status_code == 200, decision.text

        mandate = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/mandates", headers=headers, json={
            "autonomy_level": "sandbox-experiment",
            "allowed_capabilities": ["prototype.build", "prototype.verify"],
            "maximum_cost_usd": 40,
            "maximum_external_actions": 0,
            "maximum_duration_seconds": 3600,
            "reason": "Run one reversible private prototype and stop before external consequences.",
        })
        assert mandate.status_code == 200, mandate.text
        assert mandate.json()["autonomy_level"] == "sandbox-experiment"
        assert "credential-export" in mandate.json()["forbidden_capabilities"]

        converted = client.post(f"/api/opportunity-intelligence/candidates/{candidate_id}/convert-to-mission", headers=headers)
        assert converted.status_code == 200, converted.text
        assert converted.json()["metadata"]["opportunity_candidate_id"] == candidate_id
        assert converted.json()["independent_support_count"] >= 2

        console = client.get("/api/opportunity-intelligence/console", headers=headers)
        assert console.status_code == 200
        payload = console.json()
        assert payload["secret_values_exposed"] is False
        assert payload["authority"]["public_observation"] == "autonomous"
        assert payload["authority"]["high_consequence_actions"] == "explicit-action-approval"
        assert len(payload["sources"]) >= 4
        assert len(payload["mandates"]) == 1
