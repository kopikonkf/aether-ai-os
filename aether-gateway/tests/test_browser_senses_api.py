from __future__ import annotations

import importlib
import json
import struct
import sys

from fastapi.testclient import TestClient


def test_browser_senses_console_and_session_api(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "founder-browser-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AUTH_SECRET_KEY", "a" * 48)
    monkeypatch.setenv("AETHER_SENSE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("AETHER_SENSES_ORIGIN", "https://aethers.my.id")
    monkeypatch.setenv("AETHER_FLEET_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    for name in list(sys.modules):
        if name == "aether_gateway.api.server":
            sys.modules.pop(name, None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app, base_url="https://aethers.my.id") as client:
        page = client.get("/senses")
        assert page.status_code == 200
        assert "See. Hear. Speak." in page.text
        assert "founder-browser-secret" not in page.text
        assert "operatorToken" not in page.text
        assert "frame-ancestors 'self'" in page.headers["content-security-policy"]
        assert "cdn.jsdelivr.net" not in page.headers["content-security-policy"]
        assert "worker-src 'self'" in page.headers["content-security-policy"]
        assert 'rel="manifest" href="/senses/manifest.webmanifest"' in page.text
        assert 'id="resumeSenses"' in page.text
        assert page.headers["cache-control"] == "no-store"
        script = client.get("/senses/app.js")
        assert script.status_code == 200
        assert "operatorToken" not in script.text
        assert "browserToken" not in script.text
        assert "localStorage" not in script.text
        assert "sessionStorage" not in script.text
        assert "cdn.jsdelivr.net" not in script.text
        assert "./vendor/livekit-client-2.17.2.esm.js" in script.text
        turn_module = client.get("/senses/turn_generation.js")
        assert turn_module.status_code == 200
        assert "createTurnGenerationCoordinator" in turn_module.text
        vision_module = client.get("/senses/vision_capture.js")
        assert vision_module.status_code == 200
        assert "createVisionCaptureCoordinator" in vision_module.text
        assert client.get("/senses/client_state.js").status_code == 200
        assert client.get("/senses/styles.css").status_code == 200
        assert client.get("/senses/pwa_runtime.js").status_code == 200
        policy = client.get("/senses/pwa_cache_policy.js")
        assert policy.status_code == 200
        assert "NETWORK_ONLY" in policy.text
        service_worker = client.get("/senses/sw.js")
        assert service_worker.status_code == 200
        assert service_worker.headers["service-worker-allowed"] == "/senses"
        assert service_worker.headers["cache-control"] == "no-store"
        assert "AETHER_CLEAR_CACHES" in service_worker.text
        assert "NETWORK_ONLY intentionally does not call respondWith" in service_worker.text
        manifest_response = client.get("/senses/manifest.webmanifest")
        assert manifest_response.status_code == 200
        assert manifest_response.headers["content-type"].startswith(
            "application/manifest+json"
        )
        manifest = json.loads(manifest_response.text)
        assert manifest["id"] == "/senses"
        assert manifest["start_url"] == "/senses"
        assert manifest["scope"] == "/senses"
        assert manifest["display"] == "standalone"
        assert {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]} == {
            ("192x192", "any"),
            ("512x512", "any"),
            ("512x512", "maskable"),
        }
        for icon in manifest["icons"]:
            icon_response = client.get(icon["src"])
            assert icon_response.status_code == 200
            assert icon_response.headers["content-type"].startswith("image/png")
            assert icon_response.content.startswith(b"\x89PNG\r\n\x1a\n")
            assert struct.unpack(">II", icon_response.content[16:24]) == tuple(
                int(value) for value in icon["sizes"].split("x")
            )
        assert client.get("/senses/icons/not-allowlisted.png").status_code == 404
        vendor = client.get("/senses/vendor/livekit-client-2.17.2.esm.js")
        assert vendor.status_code == 200
        assert vendor.headers["content-type"].startswith("application/javascript")
        assert len(vendor.content) > 100_000
        status = client.get("/api/browser-senses/status").json()
        assert status["policy_id"] == "aether.browser-senses.v1"
        assert status["bootstrap"]["policy_id"] == "aether.browser-senses.bootstrap.v1"
        assert status["bootstrap"]["secrets_exposed"] is False
        assert status["vision"]["consent_lease_seconds"] == 900
        assert status["vision"]["capture_interval_seconds"] == 15
        assert status["vision"]["orphan_maximum_age_seconds"] == 300
        assert status["vision"]["continuous_video_transmission"] is False
        assert client.get("/api/browser-senses/status").headers["cache-control"] == "no-store"
        assert client.get("/health").headers["cache-control"] == "no-store"

        denied_preflight = client.options(
            "/api/browser-senses/bootstrap/requests",
            headers={
                "Origin": "https://attacker.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert denied_preflight.status_code == 400
        assert "access-control-allow-origin" not in denied_preflight.headers
        allowed_preflight = client.options(
            "/api/browser-senses/bootstrap/requests",
            headers={
                "Origin": "https://aethers.my.id",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert allowed_preflight.status_code == 200
        assert (
            allowed_preflight.headers["access-control-allow-origin"]
            == "https://aethers.my.id"
        )

        assert client.post("/api/browser-senses/session", json={}).status_code == 403
        operator_header_cannot_issue = client.post(
            "/api/browser-senses/session",
            headers={
                "Origin": "https://aethers.my.id",
                "Sec-Fetch-Site": "same-origin",
                "X-Aether-Operator-Token": "founder-browser-secret",
            },
            json={
                "display_name": "Founder",
                "capabilities": ["text", "camera"],
                "challenge_id": "not-device-proof",
                "device_signature": "not-device-proof",
            },
        )
        assert operator_header_cannot_issue.status_code == 401
