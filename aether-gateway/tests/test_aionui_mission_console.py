from __future__ import annotations

import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_mission_console_assets_and_authenticated_snapshot(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "mission-console-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    for name in ("AETHER_CODEX_BIN", "AETHER_OPENCODE_BIN", "AETHER_GEMINI_BIN", "AETHER_CLAUDE_BIN"):
        monkeypatch.setenv(name, str(tmp_path / f"missing-{name.casefold()}"))
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")

    with TestClient(server.app) as client:
        html = client.get("/aionui/mission-console")
        assert html.status_code == 200
        assert "Mission Console" in html.text
        assert "claimed value from verified revenue" in html.text
        assert "mission-console-fixture" not in html.text
        assert client.get("/aionui/mission-console/app.js").status_code == 200
        assert client.get("/aionui/mission-console/styles.css").status_code == 200
        manifest = client.get("/aionui/mission-console/manifest.json").json()
        assert manifest["authority"] == "operator-shell-only"
        assert manifest["claimed_value_is_revenue"] is False

        assert client.get("/api/mission-operations/console").status_code == 401
        response = client.get(
            "/api/mission-operations/console",
            headers={"X-Aether-Operator-Token": "mission-console-fixture"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["operator"] == "founder"
        assert payload["status"]["missions"] == 0
        assert payload["authority"]["claimed_value_is_not_revenue"] is True
        assert payload["authority"]["model_self_approval"] == "forbidden"
        assert payload["secret_values_exposed"] is False
        assert "mission-console-fixture" not in response.text
