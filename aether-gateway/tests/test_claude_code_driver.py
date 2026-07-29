from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

from aether.contracts import RuntimeCommand, RuntimeConformanceState, RuntimeDriverAvailability
from aether_gateway.runtime_drivers import RuntimeDriverPack
from aether_gateway.runtime_sdk import ExternalStreamingCodingRuntimeAdapter, RuntimeTelemetryStore


def _fake_claude(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n print('2.1.7 (Claude Code)'); raise SystemExit(0)\n"
        "assert '-p' in sys.argv and '--output-format' in sys.argv and 'stream-json' in sys.argv\n"
        "assert '--verbose' in sys.argv and '--max-turns' in sys.argv and '--model' in sys.argv\n"
        "assert '--allowedTools' in sys.argv and '--disallowedTools' in sys.argv\n"
        "allowed=sys.argv[sys.argv.index('--allowedTools')+1]\n"
        "denied=sys.argv[sys.argv.index('--disallowedTools')+1]\n"
        "assert 'Edit' in allowed and 'Bash' in denied and 'WebFetch' in denied\n"
        "secret=os.environ['ANTHROPIC_API_KEY']\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "Path('calc.py').write_text('def add(a, b):\\n    return a + b\\n',encoding='utf-8')\n"
        "print(json.dumps({'type':'system','session_id':'c1','model':'sonnet'}),flush=True)\n"
        "print(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':'working '+secret}]}}),flush=True)\n"
        "print(json.dumps({'type':'result','subtype':'success','is_error':False,'duration_ms':10,'num_turns':1}),flush=True)\n",
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


def test_claude_code_translator_tool_allowlist_and_secret_redaction(tmp_path: Path):
    root = _workspace(tmp_path)
    binary = _fake_claude(tmp_path / "claude")
    key = tmp_path / "anthropic.key"
    secret = "claude-fixture-secret-never-persist"
    key.write_text(secret + "\n", encoding="utf-8")
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, "-m", "aether_gateway.runtime_drivers.claude_code"),
        tmp_path / "state",
        RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
        routing_key="runtime://coding/anthropic-claude-code",
        adapter_id="runtime.coding.anthropic-claude-code",
        runtime_env={
            "AETHER_CLAUDE_BIN": str(binary),
            "AETHER_CLAUDE_API_KEY_FILE": str(key),
            "AETHER_CLAUDE_MODEL": "sonnet",
        },
        environment_policy_id="aether.runtime-driver.claude.tool-allowlist-v1",
    )
    health = asyncio.run(adapter.health())
    assert health["ok"] is True
    assert "2.1.7" in health["runtime_version"]
    result = asyncio.run(adapter.execute(RuntimeCommand("coding.task.execute", {"task": _task("claude-task-1"), "workspace_binding": _binding(root)})))
    assert result.ok is True, result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    transcript = tmp_path / "state" / "runs" / "claude-task-1" / "stream.jsonl"
    text = transcript.read_text(encoding="utf-8")
    assert secret not in text
    assert "[REDACTED]" in text
    assert "artifact.patch" in text


def test_claude_code_conformance_receipt_gates_routing(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    binary = _fake_claude(tmp_path / "claude")
    key = tmp_path / "anthropic.key"
    key.write_text("fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_CLAUDE_BIN", str(binary))
    monkeypatch.setenv("AETHER_CLAUDE_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_CLAUDE_MODEL", "sonnet")
    pack = RuntimeDriverPack(tmp_path / "drivers", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"), allowed_workspace_roots=[root])
    status = {item.manifest.driver_id: item for item in pack.status()}["anthropic-claude-code"]
    assert status.availability == RuntimeDriverAvailability.AVAILABLE
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == "runtime.coding.anthropic-claude-code"][0]
    assert asyncio.run(wrapped.health())["conformance_state"] == RuntimeConformanceState.MISSING.value
    receipt = asyncio.run(pack.conform("anthropic-claude-code", principal="founder", ttl_hours=24))
    assert receipt.passed is True
    assert receipt.provider_id == "anthropic"
    assert receipt.model_id == "sonnet"
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == "runtime.coding.anthropic-claude-code"][0]
    assert asyncio.run(wrapped.health())["ok"] is True
    assert "fixture-secret" not in json.dumps(pack.as_dict(), default=str)
