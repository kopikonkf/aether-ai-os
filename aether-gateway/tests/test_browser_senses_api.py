from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_browser_senses_console_and_session_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "founder-browser-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("AETHER_SENSE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    for name in list(sys.modules):
        if name == "aether_gateway.api.server":
            sys.modules.pop(name, None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app) as client:
        page = client.get("/senses")
        assert page.status_code == 200
        assert "See. Hear. Speak." in page.text
        assert "founder-browser-secret" not in page.text
        assert client.get("/senses/app.js").status_code == 200
        assert client.get("/senses/styles.css").status_code == 200
        assert client.get("/api/browser-senses/status").json()["policy_id"] == "aether.browser-senses.v1"

        assert client.post("/api/browser-senses/session", json={}).status_code == 401
        issued = client.post(
            "/api/browser-senses/session",
            headers={"X-Aether-Operator-Token": "founder-browser-secret"},
            json={"display_name": "Founder", "capabilities": ["text", "camera"]},
        )
        assert issued.status_code == 200, issued.text
        payload = issued.json()
        assert payload["session"]["principal"] == "founder"
        assert "token_hash" not in issued.text
        assert "founder-browser-secret" not in issued.text

        token = payload["browser_session_token"]
        active = client.post(
            "/api/browser-senses/session/active",
            headers={"Authorization": f"Bearer {token}"},
            json={"transport": "http-keyframe"},
        )
        assert active.status_code == 200
        assert active.json()["state"] == "active"
