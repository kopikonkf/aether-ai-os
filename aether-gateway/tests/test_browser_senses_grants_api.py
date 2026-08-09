from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_livekit_grant_status_route_is_operator_authenticated(tmp_path, monkeypatch):
    ORIGIN = "https://aethers.my.id"
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "founder-browser-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("AETHER_SENSE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("AETHER_SENSES_ORIGIN", ORIGIN)
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    monkeypatch.delenv("LIVEKIT_API_KEY", raising=False)
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    for name in list(sys.modules):
        if name == "aether_gateway.api.server":
            sys.modules.pop(name, None)
    server = importlib.import_module("aether_gateway.api.server")
    browser_headers = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
    with TestClient(server.app, base_url=ORIGIN) as client:
        # Unauthenticated -> 401 (operator protected)
        r = client.get(
            "/api/browser-senses/livekit/grants/nope", headers=browser_headers
        )
        assert r.status_code == 401
        # Authenticated -> unknown session is just empty active grants (not a failure)
        r = client.get(
            "/api/browser-senses/livekit/grants/nope",
            headers={**browser_headers, "X-Aether-Operator-Token": "founder-browser-secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["active_grants"] == []
