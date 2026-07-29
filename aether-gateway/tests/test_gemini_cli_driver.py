from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

from aether.contracts import RuntimeCommand, RuntimeConformanceState, RuntimeDriverAvailability
from aether_gateway.runtime_drivers import RuntimeDriverPack
from aether_gateway.runtime_sdk import ExternalStreamingCodingRuntimeAdapter, RuntimeTelemetryStore


def _fake_gemini(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n print('0.11.0'); raise SystemExit(0)\n"
        "assert '-p' in sys.argv and '--output-format' in sys.argv and 'stream-json' in sys.argv\n"
        "assert '--approval-mode' in sys.argv and 'auto_edit' in sys.argv and '--sandbox' in sys.argv\n"
        "assert '--model' in sys.argv\n"
        "secret=os.environ['GEMINI_API_KEY']\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "policy=Path(os.environ['HOME'])/'.gemini'/'policies'/'aether-runtime.toml'\n"
        "assert policy.is_file() and 'run_shell_command' in policy.read_text() and 'deny' in policy.read_text()\n"
        "Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n',encoding='utf-8')\n"
        "print(json.dumps({'type':'init','session_id':'g1','model':'gemini-2.5-flash'}),flush=True)\n"
        "print(json.dumps({'type':'message','role':'assistant','content':'working '+secret}),flush=True)\n"
        "print(json.dumps({'type':'tool_use','name':'write_file'}),flush=True)\n"
        "print(json.dumps({'type':'tool_result','name':'write_file','status':'ok'}),flush=True)\n"
        "print(json.dumps({'type':'result','status':'success','stats':{'tokens':10}}),flush=True)\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    return root


def _task(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "objective": "Fix add so the held-out test passes.",
        "workspace_id": "w1",
        "session_id": "s1",
        "edits": [],
        "verification_commands": [{"argv": [sys.executable, "-m", "pytest", "-q", "test_calc.py"], "label": "heldout"}],
        "required_capabilities": ["coding.patch-generation"],
        "required_runtime_features": ["generative-coding", "runtime-generated-patch"],
        "max_artifacts": 10,
        "max_total_bytes": 262144,
    }


def _binding(root: Path) -> dict:
    return {"workspace_id": "w1", "root_path": str(root), "session_id": "s1", "allowed_relative_paths": ["."], "writable": True}


def test_gemini_translator_policy_stream_and_secret_redaction(tmp_path: Path):
    root = _workspace(tmp_path)
    binary = _fake_gemini(tmp_path / "gemini")
    key = tmp_path / "gemini.key"
    secret = "gemini-fixture-secret-never-persist"
    key.write_text(secret + "\n", encoding="utf-8")
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, "-m", "aether_gateway.runtime_drivers.gemini_cli"),
        tmp_path / "state",
        RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
        routing_key="runtime://coding/google-gemini-cli",
        adapter_id="runtime.coding.google-gemini-cli",
        runtime_env={
            "AETHER_GEMINI_BIN": str(binary),
            "AETHER_GEMINI_API_KEY_FILE": str(key),
            "AETHER_GEMINI_MODEL": "gemini-2.5-flash",
        },
        environment_policy_id="aether.runtime-driver.gemini.policy-file-v1",
    )
    health = asyncio.run(adapter.health())
    assert health["ok"] is True
    assert health["runtime_version"] == "0.11.0"
    result = asyncio.run(adapter.execute(RuntimeCommand("coding.task.execute", {"task": _task("gemini-task-1"), "workspace_binding": _binding(root)})))
    assert result.ok is True, result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    transcript = tmp_path / "state" / "runs" / "gemini-task-1" / "stream.jsonl"
    text = transcript.read_text(encoding="utf-8")
    assert secret not in text
    assert "[REDACTED]" in text
    assert "artifact.patch" in text


def test_gemini_conformance_receipt_gates_routing(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    binary = _fake_gemini(tmp_path / "gemini")
    key = tmp_path / "gemini.key"
    key.write_text("fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_GEMINI_BIN", str(binary))
    monkeypatch.setenv("AETHER_GEMINI_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_GEMINI_MODEL", "gemini-2.5-flash")
    pack = RuntimeDriverPack(tmp_path / "drivers", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"), allowed_workspace_roots=[root])
    status = {item.manifest.driver_id: item for item in pack.status()}["google-gemini-cli"]
    assert status.availability == RuntimeDriverAvailability.AVAILABLE
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == "runtime.coding.google-gemini-cli"][0]
    assert asyncio.run(wrapped.health())["conformance_state"] == RuntimeConformanceState.MISSING.value
    receipt = asyncio.run(pack.conform("google-gemini-cli", principal="founder", ttl_hours=24))
    assert receipt.passed is True
    assert receipt.provider_id == "google-gemini"
    assert receipt.model_id == "gemini-2.5-flash"
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == "runtime.coding.google-gemini-cli"][0]
    assert asyncio.run(wrapped.health())["ok"] is True
    assert "fixture-secret" not in json.dumps(pack.as_dict(), default=str)
