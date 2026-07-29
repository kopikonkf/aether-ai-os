from __future__ import annotations

import importlib
import json
import stat
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _fake_opencode(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "if '--version' in sys.argv:\n print('opencode 1.18.4'); raise SystemExit(0)\n"
        "cfg=json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])\n"
        "assert cfg['provider']['opencode']['options']['apiKey'].startswith('{file:')\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "open('calc.py','w',encoding='utf-8').write('def add(a, b):\\n    return a + b\\n')\n"
        "print(json.dumps({'type':'session.started'}),flush=True)\n"
        "print(json.dumps({'type':'tool','part':{'type':'tool','name':'edit'}}),flush=True)\n"
        "print(json.dumps({'type':'result','status':'ok'}),flush=True)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_opencode_driver_api_conformance_approval_and_patch(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    target = workspace / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2,3) == 5\n", encoding="utf-8",
    )
    binary = _fake_opencode(tmp_path / "opencode")
    key = tmp_path / "zen.key"
    secret = "api-fixture-secret-never-persist"
    key.write_text(secret + "\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "opencode-api-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(binary))
    monkeypatch.setenv("AETHER_OPENCODE_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_OPENCODE_MODEL", "opencode/north-mini-code-free")
    monkeypatch.setenv("AETHER_CODEX_BIN", str(tmp_path / "missing-codex"))
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token": "opencode-api-fixture"}
    with TestClient(server.app) as client:
        status = client.get("/api/runtime-drivers/status", headers=headers)
        assert status.status_code == 200
        drivers = {item["manifest"]["driver_id"]: item for item in status.json()["drivers"]}
        assert drivers["opencode-cli"]["availability"] == "available"
        assert drivers["opencode-cli"]["metadata"]["conformance_state"] == "missing"
        assert secret not in status.text

        conformed = client.post("/api/runtime-drivers/opencode-cli/conform", headers=headers, json={"ttl_hours": 24})
        assert conformed.status_code == 200, conformed.text
        assert conformed.json()["routing_eligible"] is True
        assert secret not in conformed.text

        bound = client.post("/api/runtimes/workspaces/bind", headers=headers, json={
            "root_path": str(workspace), "session_id": "api:opencode", "workspace_id": "opencode-workspace",
            "allowed_relative_paths": ["."], "writable": True,
        })
        assert bound.status_code == 200, bound.text
        requested = client.post("/api/runtimes/coding/tasks", headers=headers, json={
            "objective": "Fix calc.py so the held-out addition test passes.",
            "workspace_id": "opencode-workspace", "session_id": "api:opencode", "edits": [],
            "verification_commands": [{"argv": [sys.executable, "-m", "pytest", "-q", "test_calc.py"], "label": "heldout"}],
            "allow_fallback": False,
        })
        assert requested.status_code == 200, requested.text
        payload = requested.json()
        assert payload["status"] == "pending-approval"
        assert payload["selected_runtime_id"] == "runtime.coding.opencode-cli"
        approval_id = payload["pending_approval"]["approval_id"]
        approved = client.post(
            f"/api/approvals/{approval_id}/approve", headers=headers,
            json={"reason": "Reviewed exact OpenCode task, receipt, workspace binding, and held-out verification."},
        )
        assert approved.status_code == 200, approved.text
        result = approved.json()["approval"]["result"]
        assert result["ok"] is True
        assert result["metadata"]["selected_runtime_adapter_id"] == "runtime.coding.opencode-cli"
        assert result["metadata"]["conformance_receipt_id"]
        assert target.read_text(encoding="utf-8").endswith("return a + b\n")
        assert secret not in approved.text
