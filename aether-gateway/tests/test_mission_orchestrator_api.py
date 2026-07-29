from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_mission_api_governs_plan_execution_and_verified_value(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "mission-api-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "mission-api-secret"}

    with TestClient(server.app) as client:
        assert client.get("/api/missions").status_code == 401
        intake = client.post(
            "/api/opportunities",
            headers=headers,
            json={
                "title": "Bounded external-value validation",
                "lane": "external-value",
                "problem_statement": "A small customer segment has a repetitive process.",
                "beneficiary": "Small operators",
                "value_proposition": "Deliver a bounded automation proof.",
                "probability_success": 0.6,
                "upside_usd": 100.0,
                "estimated_cost_usd": 10.0,
                "estimated_duration_hours": 1.0,
                "revenue_hypothesis": "One customer pays USD 100 after accepting the bounded proof.",
                "assumptions": ["The customer confirms the problem."],
                "evidence": [
                    {"source": "interview-a", "independent_source_id": "a", "statement": "Operator A reports the workflow problem.", "external_reference": "evidence://a"},
                    {"source": "interview-b", "independent_source_id": "b", "statement": "Operator B reports the same problem.", "external_reference": "evidence://b"},
                ],
                "risk": "low",
                "confidence": 0.6,
            },
        )
        assert intake.status_code == 200, intake.text
        brief = intake.json()
        assert brief["blockers"] == []

        plan_response = client.post(
            "/api/missions/plans",
            headers=headers,
            json={
                "brief_id": brief["brief_id"],
                "objective": "Validate the opportunity with one governed runtime step.",
                "northstar_alignment": "Evidence-first, bounded, reversible value experiment.",
                "northstar_principle_ids": ["SP1", "SP5"],
                "strategy_tags": ["business_experimentation"],
                "steps": [
                    {
                        "step_id": "validate-runtime",
                        "title": "Run bounded validation",
                        "target": "runtime",
                        "operation": "echo",
                        "arguments": {"text": "external value experiment validated"},
                        "required_scopes": ["execute"],
                        "reason": "Collect one governed execution receipt.",
                        "risk": "low",
                        "reversible": True,
                        "success_criteria": ["Runtime returns a completed result."],
                        "estimated_cost_usd": 1.0,
                    }
                ],
                "budget": {"max_cost_usd": 5.0, "max_duration_seconds": 300, "max_step_attempts": 3, "max_high_risk_actions": 0, "minimum_expected_value_usd": 0.0},
                "stop_conditions": ["Stop on failure."]
            },
        )
        assert plan_response.status_code == 200, plan_response.text
        mission_id = plan_response.json()["plan"]["mission_id"]
        assert plan_response.json()["status"] == "review-required"

        approved = client.post(f"/api/missions/{mission_id}/approve", headers=headers, json={"reason": "Reviewed evidence, expected value, and bounded budget."})
        assert approved.status_code == 200, approved.text
        assert approved.json()["mission"]["status"] == "approved"

        run = client.post(f"/api/missions/{mission_id}/run", headers=headers, json={"maximum_steps": 5})
        assert run.status_code == 200, run.text
        assert run.json()["execution"]["status"] == "completed"
        assert run.json()["execution"]["completed_step_ids"] == ["validate-runtime"]

        claimed = client.post(f"/api/missions/{mission_id}/value-evidence", headers=headers, json={
            "kind": "claimed", "description": "Estimated customer benefit", "source": "analysis", "amount_usd": 500.0
        })
        assert claimed.status_code == 200
        realized = client.post(f"/api/missions/{mission_id}/value-evidence", headers=headers, json={
            "kind": "realized", "description": "External payment receipt", "source": "payment-provider",
            "amount_usd": 100.0, "external_reference": "receipt://external-1"
        })
        assert realized.status_code == 200, realized.text
        verified = client.post(f"/api/missions/{mission_id}/value-evidence", headers=headers, json={
            "kind": "verified", "description": "Founder verified payment receipt", "source": "founder-review",
            "amount_usd": 100.0, "external_reference": "receipt://external-1", "related_evidence_id": realized.json()["evidence_id"]
        })
        assert verified.status_code == 200, verified.text

        outcome = client.post(f"/api/missions/{mission_id}/outcome", headers=headers, json={
            "achieved": True, "summary": "One bounded experiment produced verified revenue.",
            "lessons": ["Demand evidence must precede scaling."]
        })
        assert outcome.status_code == 200, outcome.text
        assert outcome.json()["claimed_value_usd"] == 500.0
        assert outcome.json()["realized_revenue_usd"] == 100.0
        assert outcome.json()["verified_revenue_usd"] == 100.0
        assert outcome.json()["state"] == "verified"

        mission = client.get(f"/api/missions/{mission_id}", headers=headers)
        assert mission.status_code == 200
        assert mission.json()["outcome"]["state"] == "verified"
        assert mission.json()["brief"]["expected_net_value_usd"] == 50.0
