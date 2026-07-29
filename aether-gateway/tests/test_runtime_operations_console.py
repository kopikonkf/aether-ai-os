from __future__ import annotations

import asyncio
import importlib
import json
import stat
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from aether_gateway.runtime_drivers import RuntimeDriverPack
from aether_gateway.runtime_sdk import RuntimeTelemetryStore


def _fake_version_cli(path: Path, version: str) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"print({version!r})\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_operations_console_classifies_quota_and_renews_due_receipts(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"; workspace.mkdir()
    gemini = _fake_version_cli(tmp_path / "gemini", "0.11.0")
    claude = _fake_version_cli(tmp_path / "claude", "2.1.7")
    gemini_key = tmp_path / "gemini.key"; gemini_key.write_text("gemini-console-secret\n", encoding="utf-8")
    claude_key = tmp_path / "claude.key"; claude_key.write_text("claude-console-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_GEMINI_BIN", str(gemini))
    monkeypatch.setenv("AETHER_GEMINI_API_KEY_FILE", str(gemini_key))
    monkeypatch.setenv("AETHER_CLAUDE_BIN", str(claude))
    monkeypatch.setenv("AETHER_CLAUDE_API_KEY_FILE", str(claude_key))
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    telemetry.record_invocation(
        task_id="gemini-rate-limit", adapter_id="runtime.coding.google-gemini-cli", workspace_id="w", session_id="s",
        ok=False, status="failed", duration_seconds=1.0, artifact_count=0, verification_count=0,
        failure_fingerprint="rate-limit", payload={"error": "HTTP 429 rate limit exceeded"},
    )
    pack = RuntimeDriverPack(tmp_path / "drivers", telemetry, allowed_workspace_roots=[workspace])
    asyncio.run(pack.conform("google-gemini-cli", principal="founder", ttl_hours=1))
    asyncio.run(pack.conform("anthropic-claude-code", principal="founder", ttl_hours=1))
    console = pack.operations_console()
    drivers = {item["driver_id"]: item for item in console["drivers"]}
    assert drivers["google-gemini-cli"]["quota_state"] == "rate-limited"
    assert drivers["google-gemini-cli"]["metadata"]["quota_priority_penalty"] == 15
    assert drivers["anthropic-claude-code"]["quota_state"] == "healthy"
    assert drivers["anthropic-claude-code"]["routing_eligible"] is True
    assert console["renewal_due_count"] >= 2
    rendered = json.dumps(console, default=str)
    assert "gemini-console-secret" not in rendered
    assert "claude-console-secret" not in rendered
    renewed = asyncio.run(pack.renew_due_receipts(principal="founder", ttl_hours=24))
    assert {item.driver_id for item in renewed} >= {"google-gemini-cli", "anthropic-claude-code"}


def test_runtime_operations_console_api_is_operator_authenticated(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"; workspace = home / "workspace"; workspace.mkdir(parents=True)
    gemini = _fake_version_cli(tmp_path / "gemini", "0.11.0")
    key = tmp_path / "gemini.key"; key.write_text("api-console-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "runtime-console-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_GEMINI_BIN", str(gemini))
    monkeypatch.setenv("AETHER_GEMINI_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_CODEX_BIN", str(tmp_path / "missing-codex"))
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(tmp_path / "missing-opencode"))
    monkeypatch.setenv("AETHER_CLAUDE_BIN", str(tmp_path / "missing-claude"))
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    with TestClient(server.app) as client:
        assert client.get("/api/runtime-operations/console").status_code == 401
        headers = {"X-Aether-Operator-Token": "runtime-console-fixture"}
        response = client.get("/api/runtime-operations/console", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["operator"] == "founder"
        assert response.json()["secret_values_exposed"] is False
        assert "api-console-secret" not in response.text
        conformed = client.post("/api/runtime-drivers/google-gemini-cli/conform", headers=headers, json={"ttl_hours": 1})
        assert conformed.status_code == 200, conformed.text
        refreshed = client.post("/api/runtime-operations/refresh", headers=headers, json={"renew_due_receipts": True, "ttl_hours": 24})
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["routing_eligible_count"] >= 1
        assert "api-console-secret" not in refreshed.text
