from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_evolution_api_requires_trusted_operator_and_supports_promote_rollback(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "heldout").mkdir()
    target = workspace / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "tests" / "test_add.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class AddTest(unittest.TestCase):\n"
        "    def test_positive(self): self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    (workspace / "heldout" / "test_edge.py").write_text(
        "import unittest\nfrom calculator import add\n"
        "class EdgeTest(unittest.TestCase):\n"
        "    def test_zero(self): self.assertEqual(add(0, 1), 1)\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_EVOLUTION_WORKSPACE", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "evolution-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "evolution-secret"}

    with TestClient(server.app) as client:
        assert client.get("/api/evolution/status").status_code == 401
        trigger = client.post(
            "/api/evolution/triggers",
            headers=headers,
            json={
                "trigger_type": "capability-gap",
                "summary": "Addition returns subtraction.",
                "target": "calculator.py",
                "evidence_ids": ["api.test.failure"],
            },
        )
        assert trigger.status_code == 200
        trigger_id = trigger.json()["trigger_id"]

        candidate = client.post(
            "/api/evolution/candidates",
            headers=headers,
            json={
                "trigger_id": trigger_id,
                "target_type": "code",
                "target_path": "calculator.py",
                "candidate_content": "def add(a, b):\n    return a + b\n",
                "rationale": "Correct the bounded arithmetic implementation.",
                "generator_id": "generator.api-test",
                "deterministic_checks": [
                    {"name": "unit", "argv": ["{python}", "-m", "unittest", "discover", "-s", "tests"]}
                ],
                "heldout_checks": [
                    {"name": "heldout", "argv": ["{python}", "-m", "unittest", "discover", "-s", "heldout"]}
                ],
            },
        )
        assert candidate.status_code == 200, candidate.text
        candidate_id = candidate.json()["candidate_id"]
        assert candidate.json()["status"] == "proposed"

        evaluation = client.post(f"/api/evolution/candidates/{candidate_id}/evaluate", headers=headers)
        assert evaluation.status_code == 200, evaluation.text
        assert evaluation.json()["status"] == "verified"
        assert evaluation.json()["evaluation"]["improvement"] == 1.0

        promoted = client.post(
            f"/api/evolution/candidates/{candidate_id}/approve",
            headers=headers,
            json={"reason": "Deterministic and held-out suites prove measurable improvement with zero regressions."},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["status"] == "promoted"
        lineage_id = promoted.json()["lineage"]["lineage_id"]
        assert "return a + b" in target.read_text(encoding="utf-8")

        rollback = client.post(
            f"/api/evolution/lineage/{lineage_id}/rollback",
            headers=headers,
            json={"reason": "Rollback verifies recovery from a post-promotion operational signal."},
        )
        assert rollback.status_code == 200, rollback.text
        assert rollback.json()["rolled_back_at"]
        assert "return a - b" in target.read_text(encoding="utf-8")

        listed = client.get("/api/evolution/candidates", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["candidates"][0]["status"] == "rolled-back"
