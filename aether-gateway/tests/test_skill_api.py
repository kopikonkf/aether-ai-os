from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_skill_api_supports_benchmark_activation_usage_and_archive(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    tests = workspace / "tests"
    heldout = workspace / "heldout"
    tests.mkdir(parents=True)
    heldout.mkdir()
    body = (
        "import json\nfrom pathlib import Path\n"
        "class SkillTest:\n"
        "    pass\n"
        "def test_manifest():\n"
        "    path = Path('.aether/skills/math-helper.json')\n"
        "    assert path.exists()\n"
        "    data = json.loads(path.read_text())\n"
        "    assert 'Add two integers' in data['instructions']\n"
    )
    (tests / "test_skill.py").write_text(body, encoding="utf-8")
    (heldout / "test_skill_heldout.py").write_text(body.replace("test_manifest", "test_manifest_heldout"), encoding="utf-8")

    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_SKILL_WORKSPACE", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "skill-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "skill-secret"}

    with TestClient(server.app) as client:
        assert client.get("/api/skills/status").status_code == 401
        candidate = client.post(
            "/api/skills/candidates",
            headers=headers,
            json={
                "name": "math-helper",
                "version": "1.0.0",
                "summary": "Deterministic integer addition workflow.",
                "instructions": "Add two integers and return the exact result.",
                "capabilities": ["reason"],
                "trigger_type": "repeated-success",
                "trigger_fingerprint": "workflow:add-integers",
                "evidence_ids": ["evt-1", "evt-2", "evt-3"],
                "observed_count": 3,
                "successful_count": 3,
                "source_workflow": "manual-addition",
                "generator_id": "generator.api-test",
                "rationale": "Repeated successful workflow should become a governed reusable skill.",
                "deterministic_checks": [
                    {"name": "unit", "argv": ["{python}", "-m", "pytest", "-q", "tests/test_skill.py"]}
                ],
                "heldout_checks": [
                    {"name": "heldout", "argv": ["{python}", "-m", "pytest", "-q", "heldout/test_skill_heldout.py"]}
                ],
            },
        )
        assert candidate.status_code == 200, candidate.text
        candidate_id = candidate.json()["candidate_id"]
        assert candidate.json()["status"] == "draft"

        benchmark = client.post(f"/api/skills/candidates/{candidate_id}/benchmark", headers=headers)
        assert benchmark.status_code == 200, benchmark.text
        assert benchmark.json()["status"] == "verified"
        assert benchmark.json()["benchmark"]["improvement"] == 1.0

        activated = client.post(
            f"/api/skills/candidates/{candidate_id}/activate",
            headers=headers,
            json={"reason": "Held-out benchmark proves a reusable bounded workflow with zero regressions."},
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["status"] == "active"
        skill_id = activated.json()["record"]["skill_id"]
        install_path = Path(activated.json()["record"]["install"]["install_path"])
        assert install_path.exists()

        usage = client.post(
            f"/api/skills/{skill_id}/usage",
            headers=headers,
            json={"runtime_id": "runtime.test", "success": True, "duration_seconds": 0.2},
        )
        assert usage.status_code == 200
        listed = client.get("/api/skills", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["skills"][0]["usage_count"] == 1

        archived = client.post(
            f"/api/skills/{skill_id}/archive",
            headers=headers,
            json={"reason": "Archive after explicit operator review while retaining the immutable artifact."},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["lifecycle_status"] == "archived"
        assert install_path.exists()

        blocked_usage = client.post(
            f"/api/skills/{skill_id}/usage",
            headers=headers,
            json={"runtime_id": "runtime.test", "success": True},
        )
        assert blocked_usage.status_code == 409
