from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_runtime_driver_pack_api_is_authenticated_and_nonfatal(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "driver-api-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_CODEX_BIN", str(tmp_path / "missing-codex"))
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app) as client:
        denied = client.get("/api/runtime-drivers/status")
        assert denied.status_code == 401
        response = client.get("/api/runtime-drivers/status", headers={"X-Aether-Operator-Token":"driver-api-fixture"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["policy_id"] == "aether.runtime-driver-pack.v3"
        statuses = {item["manifest"]["driver_id"]: item for item in data["drivers"]}
        assert statuses["openai-codex-cli"]["availability"] == "unavailable"
        assert statuses["anthropic-claude-code"]["availability"] == "unavailable"
