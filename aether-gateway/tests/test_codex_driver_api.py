from __future__ import annotations

import importlib
import stat
import sys
from pathlib import Path

from fastapi.testclient import TestClient


def _fake_codex(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "if '--version' in sys.argv:\n print('codex-cli 0.144.1'); raise SystemExit(0)\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "_ = sys.stdin.read()\n"
        "open('calc.py','w',encoding='utf-8').write('def add(a, b):\\n    return a + b\\n')\n"
        "print(json.dumps({'type':'thread.started','thread_id':'api-thread'}),flush=True)\n"
        "print(json.dumps({'type':'turn.started'}),flush=True)\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'file_change','id':'f1'}}),flush=True)\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7,'output_tokens':3}}),flush=True)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_codex_driver_api_generates_patch_after_approval(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    target = workspace / "calc.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2,3) == 5\n", encoding="utf-8")
    binary = _fake_codex(tmp_path / "codex")
    monkeypatch.setenv("AETHER_HOME", str(home))
    monkeypatch.setenv("AETHER_CODING_WORKSPACE_ROOTS", str(workspace))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "codex-api-fixture")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("AETHER_CODEX_BIN", str(binary))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-credential")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")
    headers = {"X-Aether-Operator-Token":"codex-api-fixture"}
    with TestClient(server.app) as client:
        conformed = client.post("/api/runtime-drivers/openai-codex-cli/conform", headers=headers, json={"ttl_hours":24})
        assert conformed.status_code == 200, conformed.text
        assert conformed.json()["routing_eligible"] is True
        bound = client.post("/api/runtimes/workspaces/bind", headers=headers, json={
            "root_path":str(workspace),"session_id":"api:codex","workspace_id":"codex-workspace",
            "allowed_relative_paths":["."],"writable":True,
        })
        assert bound.status_code == 200, bound.text
        requested = client.post("/api/runtimes/coding/tasks", headers=headers, json={
            "objective":"Fix calc.py so the held-out addition test passes.",
            "workspace_id":"codex-workspace","session_id":"api:codex","edits":[],
            "verification_commands":[{"argv":[sys.executable,"-m","pytest","-q","test_calc.py"],"label":"heldout"}],
            "allow_fallback":False,
        })
        assert requested.status_code == 200, requested.text
        payload = requested.json()
        assert payload["status"] == "pending-approval"
        assert payload["selected_runtime_id"] == "runtime.coding.openai-codex-cli"
        assert target.read_text(encoding="utf-8").endswith("return a - b\n")
        approval_id = payload["pending_approval"]["approval_id"]
        approved = client.post(f"/api/approvals/{approval_id}/approve", headers=headers,
                               json={"reason":"Reviewed live driver, staging boundary, and independent test."})
        assert approved.status_code == 200, approved.text
        result = approved.json()["approval"]["result"]
        assert result["ok"] is True
        assert result["metadata"]["selected_runtime_adapter_id"] == "runtime.coding.openai-codex-cli"
        assert target.read_text(encoding="utf-8").endswith("return a + b\n")
