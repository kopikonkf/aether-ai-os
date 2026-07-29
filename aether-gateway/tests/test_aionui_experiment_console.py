from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_experiment_console_assets_authentication_and_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "experiment-console-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app) as client:
        page = client.get("/aionui/experiment-console")
        assert page.status_code == 200
        assert "Live Web Intelligence" in page.text
        assert "experiment-console-secret" not in page.text
        assert client.get("/aionui/experiment-console/app.js").status_code == 200
        assert client.get("/aionui/experiment-console/styles.css").status_code == 200
        manifest = client.get("/aionui/experiment-console/manifest.json")
        assert manifest.status_code == 200
        assert manifest.json()["id"] == "aether.live-web-experiments"
        assert manifest.json()["version"] == "0.19.2"

        assert client.get("/api/experiments/console").status_code == 401
        response = client.get(
            "/api/experiments/console",
            headers={"X-Aether-Operator-Token": "experiment-console-secret"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["authority"]["synthetic_is_not_measured"] is True
        assert payload["authority"]["external_consequence_requires_review"] is True
        assert "experiment-console-secret" not in response.text
        for source in payload["web"]["sources"]:
            assert "credential_handle" not in source
