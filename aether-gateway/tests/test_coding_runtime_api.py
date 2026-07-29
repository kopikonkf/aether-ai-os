from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def test_coding_runtime_api_binds_requires_approval_executes_and_reports(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    original = "def add(a, b):\n    return a - b\n"
    target = workspace / "calc.py"
    target.write_text(original, encoding="utf-8")
    expected = hashlib.sha256(original.encode()).hexdigest()

    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "runtime-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "runtime-secret"}

    with TestClient(server.app) as client:
        status = client.get("/api/runtimes/status", headers=headers)
        assert status.status_code == 200, status.text
        assert status.json()["runtimes"][0]["health_status"] == "healthy"
        assert "coding.edit" in status.json()["runtimes"][0]["capabilities"]

        bound = client.post("/api/runtimes/workspaces/bind", headers=headers, json={
            "root_path": str(workspace),
            "session_id": "api:coding-runtime",
            "workspace_id": "workspace-api",
            "allowed_relative_paths": ["."],
            "writable": True,
        })
        assert bound.status_code == 200, bound.text

        requested = client.post("/api/runtimes/coding/tasks", headers=headers, json={
            "objective": "Correct the addition implementation.",
            "workspace_id": "workspace-api",
            "session_id": "api:coding-runtime",
            "edits": [{
                "path": "calc.py",
                "content": "def add(a, b):\n    return a + b\n",
                "expected_sha256": expected,
            }],
            "verification_commands": [{
                "argv": ["python", "-m", "compileall", "calc.py"],
                "label": "compile",
            }],
            "required_runtime_features": ["structured-edits", "verification-receipts"],
        })
        assert requested.status_code == 200, requested.text
        payload = requested.json()
        assert payload["status"] == "pending-approval"
        assert payload["selected_runtime_id"] == "runtime.coding.external-jsonl-reference"
        approval_id = payload["pending_approval"]["approval_id"]
        assert target.read_text(encoding="utf-8") == original

        approved = client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=headers,
            json={"reason": "Reviewed exact path, content hash, and bounded verification."},
        )
        assert approved.status_code == 200, approved.text
        approval = approved.json()["approval"]
        assert approval["status"] == "consumed"
        assert approval["result"]["ok"] is True
        assert approval["result"]["output"]["artifacts"][0]["path"] == "calc.py"
        assert approval["result"]["output"]["metadata"]["external_protocol"] == "aether.coding-jsonl.v1"
        assert approval["result"]["output"]["metadata"]["patch_trusted"] is False
        assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"

        after = client.get("/api/runtimes/status", headers=headers).json()
        assert after["telemetry"]["invocations"] == 1
        assert after["telemetry"]["progress_events"] >= 4
