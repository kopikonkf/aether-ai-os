from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import sys
from pathlib import Path

from aether.contracts import RuntimeCommand, RuntimeDriverAvailability
from aether_gateway.runtime_drivers import RuntimeDriverPack
from aether_gateway.runtime_sdk import ExternalStreamingCodingRuntimeAdapter, RuntimeTelemetryStore


def _fake_codex(path: Path, *, item_warning: bool = False) -> Path:
    warning = "print(json.dumps({'type':'item.completed','item':{'id':'warn','type':'error','message':'non-fatal stream lag'}}), flush=True)" if item_warning else ""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "if '--version' in sys.argv:\n"
        " print('codex-cli 0.144.1'); raise SystemExit(0)\n"
        "prompt=sys.stdin.read()\n"
        "assert '--json' in sys.argv and '--ephemeral' in sys.argv\n"
        "assert '--sandbox' in sys.argv and 'workspace-write' in sys.argv\n"
        "assert '--ask-for-approval' in sys.argv and 'never' in sys.argv\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "p='calc.py'\n"
        "open(p,'w',encoding='utf-8').write('def add(a, b):\\n    return a + b\\n')\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-1'}), flush=True)\n"
        "print(json.dumps({'type':'turn.started'}), flush=True)\n"
        "print(json.dumps({'type':'item.completed','item':{'id':'edit-1','type':'file_change','changes':[{'path':p}]}}), flush=True)\n"
        + warning + "\n"
        "print(json.dumps({'type':'item.completed','item':{'id':'msg-1','type':'agent_message','text':'Fixed calc.py'}}), flush=True)\n"
        "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':4}}), flush=True)\n",
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


def _binding(root: Path) -> dict:
    return {"workspace_id":"w1","root_path":str(root),"session_id":"s1","allowed_relative_paths":["."],"writable":True}


def _task(task_id: str) -> dict:
    return {
        "task_id":task_id,"objective":"Fix add so the held-out test passes.","workspace_id":"w1","session_id":"s1",
        "edits":[],"verification_commands":[{"argv":[sys.executable,"-m","pytest","-q","test_calc.py"],"label":"heldout"}],
        "required_capabilities":["coding.patch-generation"],"required_runtime_features":["generative-coding","runtime-generated-patch"],
        "max_artifacts":10,"max_total_bytes":262144,
    }


def _adapter(tmp_path: Path, root: Path, binary: Path) -> ExternalStreamingCodingRuntimeAdapter:
    return ExternalStreamingCodingRuntimeAdapter(
        (sys.executable,"-m","aether_gateway.runtime_drivers.codex_cli"),
        tmp_path / "state", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root], routing_key="runtime://coding/openai-codex-cli",
        adapter_id="runtime.coding.openai-codex-cli", priority=3,
        runtime_env={"AETHER_CODEX_BIN":str(binary),"OPENAI_API_KEY":"fixture-credential"},
        environment_policy_id="aether.runtime-driver.codex.explicit-credentials-v1",
    )


def test_codex_driver_handshake_discovers_version_and_auth(tmp_path: Path):
    root = _workspace(tmp_path)
    adapter = _adapter(tmp_path, root, _fake_codex(tmp_path / "codex"))
    health = asyncio.run(adapter.health())
    assert health["ok"] is True
    assert health["degraded"] is False
    assert health["runtime_version"] == "codex-cli 0.144.1"
    assert adapter.descriptor.metadata["environment_policy_id"].endswith("explicit-credentials-v1")
    assert "OPENAI_API_KEY" in adapter.descriptor.metadata["explicit_environment_names"]
    assert "fixture-credential" not in str(adapter.descriptor.metadata)


def test_codex_driver_translates_jsonl_patch_and_verifies(tmp_path: Path):
    root = _workspace(tmp_path)
    adapter = _adapter(tmp_path, root, _fake_codex(tmp_path / "codex", item_warning=True))
    result = asyncio.run(adapter.execute(RuntimeCommand("coding.task.execute", {"task":_task("codex-task-1"),"workspace_binding":_binding(root)})))
    assert result.ok is True, result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    assert result.metadata["external_runtime_id"] == "openai.codex-cli"
    assert result.metadata["patch_trusted"] is False
    assert result.metadata["independent_verification"] is True
    assert result.output["artifacts"][0]["path"] == "calc.py"
    transcript = tmp_path / "state" / "runs" / "codex-task-1" / "stream.jsonl"
    text = transcript.read_text(encoding="utf-8")
    assert "codex-warning" in text
    assert "artifact.patch" in text


def test_driver_pack_reports_live_and_unavailable_drivers(tmp_path: Path, monkeypatch):
    binary = _fake_codex(tmp_path / "codex")
    monkeypatch.setenv("AETHER_CODEX_BIN", str(binary))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-credential")
    root = _workspace(tmp_path)
    pack = RuntimeDriverPack(tmp_path / "drivers", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"), allowed_workspace_roots=[root])
    statuses = {item.manifest.driver_id:item for item in pack.status()}
    assert statuses["openai-codex-cli"].availability == RuntimeDriverAvailability.AVAILABLE
    assert statuses["anthropic-claude-code"].availability == RuntimeDriverAvailability.UNAVAILABLE
    adapters = pack.build_live_adapters()
    assert len(adapters) == 1
    assert adapters[0].adapter_id == "runtime.coding.openai-codex-cli"


def test_missing_codex_is_non_fatal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AETHER_CODEX_BIN", str(tmp_path / "missing-codex"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = _workspace(tmp_path)
    pack = RuntimeDriverPack(tmp_path / "drivers", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"), allowed_workspace_roots=[root])
    status = {item.manifest.driver_id:item for item in pack.status()}["openai-codex-cli"]
    assert status.availability == RuntimeDriverAvailability.UNAVAILABLE
    # The adapter may still be registered as an unavailable body; Core boot does not fail.
    assert len(pack.build_live_adapters()) == 1
