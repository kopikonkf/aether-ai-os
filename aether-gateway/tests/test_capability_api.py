from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_capability_api_routes_active_skill_and_records_usage(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    body = (
        "import json\nfrom pathlib import Path\n"
        "def test_manifest():\n"
        "    p=Path('.aether/skills/greeting-skill.json')\n"
        "    assert p.exists()\n"
        "    d=json.loads(p.read_text())\n"
        "    assert d['metadata']['execution']['kind']=='template-v1'\n"
    )
    (workspace / "tests" / "test_skill.py").write_text(body, encoding="utf-8")
    (workspace / "heldout" / "test_skill_heldout.py").write_text(body.replace("test_manifest", "test_heldout"), encoding="utf-8")

    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_SKILL_WORKSPACE", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "capability-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "capability-secret"}

    with TestClient(server.app) as client:
        proposed = client.post("/api/skills/candidates", headers=headers, json={
            "name": "greeting-skill",
            "version": "1.0.0",
            "summary": "Render a deterministic greeting.",
            "instructions": "Use the bounded template runtime.",
            "capabilities": ["greet"],
            "input_schema": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            "output_schema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
            "runtime_requirements": ["aether.template-v1"],
            "trigger_type": "capability-gap",
            "trigger_fingerprint": "gap:greet",
            "evidence_ids": ["evt-1"],
            "observed_count": 1,
            "successful_count": 0,
            "generator_id": "generator.api-test",
            "rationale": "Close a measured greeting capability gap.",
            "deterministic_checks": [{"name": "unit", "argv": ["{python}", "-m", "pytest", "-q", "tests/test_skill.py"]}],
            "heldout_checks": [{"name": "heldout", "argv": ["{python}", "-m", "pytest", "-q", "heldout/test_skill_heldout.py"]}],
            "metadata": {"execution": {"kind": "template-v1", "template": "Hello, {name}!"}},
        })
        assert proposed.status_code == 200, proposed.text
        candidate_id = proposed.json()["candidate_id"]
        assert client.post(f"/api/skills/candidates/{candidate_id}/benchmark", headers=headers).status_code == 200
        activated = client.post(
            f"/api/skills/candidates/{candidate_id}/activate",
            headers=headers,
            json={"reason": "Held-out benchmark proves safe deterministic capability execution."},
        )
        assert activated.status_code == 200, activated.text
        skill_id = activated.json()["record"]["skill_id"]

        status = client.get("/api/capabilities/status", headers=headers)
        assert status.status_code == 200
        assert "greet" in status.json()["capabilities"]

        executed = client.post("/api/capabilities/execute", headers=headers, json={
            "capability": "greet",
            "input": {"name": "Rebeka"},
            "required_runtime_features": ["aether.template-v1"],
            "reason": "Execute the activated greeting skill through the capability router.",
            "session_id": "api:capability-test",
        })
        assert executed.status_code == 200, executed.text
        payload = executed.json()
        assert payload["status"] == "completed"
        assert payload["output"] == {"text": "Hello, Rebeka!"}
        assert payload["selected_skill_id"] == skill_id

        record = client.get(f"/api/skills/{skill_id}", headers=headers)
        assert record.json()["usage_count"] == 1

        missing = client.post("/api/capabilities/execute", headers=headers, json={
            "capability": "missing.capability",
            "input": {},
            "reason": "Verify missing capability failure fingerprinting.",
        })
        assert missing.status_code == 409
        assert missing.json()["detail"]["failure_fingerprint"]
