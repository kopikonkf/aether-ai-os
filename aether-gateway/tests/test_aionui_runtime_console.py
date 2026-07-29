from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_native_console_assets_and_fleet_api(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "aionui-console-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("AETHER_CODEX_BIN", str(tmp_path / "missing-codex"))
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(tmp_path / "missing-opencode"))
    monkeypatch.setenv("AETHER_GEMINI_BIN", str(tmp_path / "missing-gemini"))
    monkeypatch.setenv("AETHER_CLAUDE_BIN", str(tmp_path / "missing-claude"))
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")

    with TestClient(server.app) as client:
        html = client.get("/aionui/runtime-console")
        assert html.status_code == 200
        assert "Fleet Console" in html.text
        assert "aionui-console-fixture" not in html.text
        assert "session storage only" in html.text
        assert client.get("/aionui/runtime-console/app.js").status_code == 200
        assert client.get("/aionui/runtime-console/styles.css").status_code == 200
        assert client.get("/aionui/runtime-console/manifest.json").json()["authority"] == "operator-shell-only"

        assert client.get("/api/runtime-fleet/console").status_code == 401
        headers = {"X-Aether-Operator-Token": "aionui-console-fixture"}
        console = client.get("/api/runtime-fleet/console", headers=headers)
        assert console.status_code == 200, console.text
        payload = console.json()
        assert payload["operator"] == "founder"
        assert payload["scheduler"]["enabled"] is False
        assert len(payload["jobs"]) == 4
        assert payload["secret_values_exposed"] is False

        changed = client.patch(
            "/api/runtime-fleet/jobs/health-probe",
            headers=headers,
            json={"enabled": False, "interval_seconds": 30},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["job"]["state"] == "paused"

        run = client.post("/api/runtime-fleet/jobs/health-probe/run", headers=headers)
        assert run.status_code == 200, run.text
        incidents = [item for item in run.json()["incidents"] if item["state"] != "resolved"]
        assert incidents
        incident_id = incidents[0]["incident_id"]
        ack = client.post(
            f"/api/runtime-fleet/incidents/{incident_id}/acknowledge",
            headers=headers,
            json={"reason": "Reviewed in native console"},
        )
        assert ack.status_code == 200
        assert ack.json()["incident"]["state"] == "acknowledged"
        resolved = client.post(
            f"/api/runtime-fleet/incidents/{incident_id}/resolve",
            headers=headers,
            json={"reason": "Handled by operator"},
        )
        assert resolved.status_code == 200
        assert resolved.json()["incident"]["state"] == "resolved"

        cost = client.post(
            "/api/runtime-fleet/cost-events",
            headers=headers,
            json={"driver_id": "fixture", "cost_usd": 0.25, "source": "test"},
        )
        assert cost.status_code == 200
        assert cost.json()["budget"]["known_cost_usd"] >= 0.25
        assert "aionui-console-fixture" not in cost.text
