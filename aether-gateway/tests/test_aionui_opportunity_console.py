from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_opportunity_console_assets_and_authentication(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "console-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app) as client:
        page = client.get("/aionui/opportunity-console")
        assert page.status_code == 200
        assert "Opportunity Intelligence" in page.text
        assert "operatorToken" not in page.text
        assert client.get("/aionui/opportunity-console/app.js").status_code == 200
        assert client.get("/aionui/opportunity-console/styles.css").status_code == 200
        assert client.get("/api/opportunity-intelligence/console").status_code == 401
        data = client.get("/api/opportunity-intelligence/console", headers={"X-Aether-Operator-Token": "console-secret"})
        assert data.status_code == 200
        assert data.json()["secret_values_exposed"] is False
