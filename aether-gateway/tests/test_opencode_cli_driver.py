from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

from aether.contracts import RuntimeCommand, RuntimeConformanceState, RuntimeDriverAvailability
from aether_gateway.runtime_drivers import RuntimeDriverPack
from aether_gateway.runtime_sdk import ExternalStreamingCodingRuntimeAdapter, RuntimeTelemetryStore


def _fake_opencode(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "if '--version' in sys.argv:\n"
        " print('opencode 1.18.4'); raise SystemExit(0)\n"
        "assert 'run' in sys.argv and '--format' in sys.argv and 'json' in sys.argv\n"
        "assert '--model' in sys.argv and '--dir' in sys.argv and '--auto' in sys.argv\n"
        "cfg=json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])\n"
        "ref=cfg['provider']['opencode']['options']['apiKey']\n"
        "assert ref.startswith('{file:') and ref.endswith('}')\n"
        "key_path=ref[6:-1]\n"
        "secret=open(key_path,encoding='utf-8').read().strip()\n"
        "assert secret not in os.environ['OPENCODE_CONFIG_CONTENT']\n"
        "assert not os.environ.get('AETHER_OPERATOR_TOKEN')\n"
        "open('calc.py','w',encoding='utf-8').write('def add(a, b):\\n    return a + b\\n')\n"
        "print(json.dumps({'type':'session.started','sessionID':'s1'}),flush=True)\n"
        "print(json.dumps({'type':'text','part':{'type':'text','text':'working '+secret}}),flush=True)\n"
        "print(json.dumps({'type':'tool','part':{'type':'tool','name':'edit'}}),flush=True)\n"
        "print(json.dumps({'type':'result','status':'ok'}),flush=True)\n",
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


def test_opencode_translator_uses_file_reference_and_redacts_secret(tmp_path: Path):
    root = _workspace(tmp_path)
    binary = _fake_opencode(tmp_path / "opencode")
    key = tmp_path / "zen.key"
    secret = "fixture-secret-that-must-never-appear"
    key.write_text(secret + "\n", encoding="utf-8")
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, "-m", "aether_gateway.runtime_drivers.opencode_cli"),
        tmp_path / "state",
        RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
        routing_key="runtime://coding/opencode-cli",
        adapter_id="runtime.coding.opencode-cli",
        runtime_env={
            "AETHER_OPENCODE_BIN": str(binary),
            "AETHER_OPENCODE_API_KEY_FILE": str(key),
            "AETHER_OPENCODE_MODEL": "opencode/north-mini-code-free",
        },
        environment_policy_id="aether.runtime-driver.opencode.file-credential-v1",
    )
    health = asyncio.run(adapter.health())
    assert health["ok"] is True
    assert health["runtime_version"] == "opencode 1.18.4"
    result = asyncio.run(adapter.execute(RuntimeCommand("coding.task.execute", {"task": _task("open-task-1"), "workspace_binding": _binding(root)})))
    assert result.ok is True, result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    transcript = tmp_path / "state" / "runs" / "open-task-1" / "stream.jsonl"
    text = transcript.read_text(encoding="utf-8")
    assert secret not in text
    assert "[REDACTED]" in text
    assert "artifact.patch" in text


def test_opencode_conformance_receipt_gates_routing_and_stales_on_binary_change(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    binary = _fake_opencode(tmp_path / "opencode")
    key = tmp_path / "zen.key"
    key.write_text("fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(binary))
    monkeypatch.setenv("AETHER_OPENCODE_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_OPENCODE_MODEL", "opencode/north-mini-code-free")
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    pack = RuntimeDriverPack(tmp_path / "drivers", telemetry, allowed_workspace_roots=[root])
    status = {item.manifest.driver_id: item for item in pack.status()}["opencode-cli"]
    assert status.availability == RuntimeDriverAvailability.AVAILABLE
    adapter = {item.driver_id: item for item in pack.manifests}["opencode-cli"]
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == adapter.adapter_id][0]
    health_before = asyncio.run(wrapped.health())
    assert health_before["ok"] is False
    assert health_before["conformance_state"] == RuntimeConformanceState.MISSING.value

    receipt = asyncio.run(pack.conform("opencode-cli", principal="founder", ttl_hours=24))
    assert receipt.passed is True
    assert receipt.model_id == "opencode/north-mini-code-free"
    assert "fixture-secret" not in json.dumps(pack.as_dict(), default=str)
    health_after = asyncio.run(wrapped.health())
    assert health_after["ok"] is True
    result = asyncio.run(wrapped.execute(RuntimeCommand("coding.task.execute", {"task": _task("open-task-2"), "workspace_binding": _binding(root)})))
    assert result.ok is True, result.error
    assert result.metadata["conformance_receipt_id"] == receipt.receipt_id

    # Credential reference metadata changes invalidate the receipt without
    # persisting or hashing the credential value itself.
    key.write_text("rotated-fixture-secret\n", encoding="utf-8")
    config_stale = asyncio.run(wrapped.health())
    assert config_stale["ok"] is False
    assert config_stale["conformance_state"] == RuntimeConformanceState.STALE.value

    refreshed = asyncio.run(pack.conform("opencode-cli", principal="founder", ttl_hours=24))
    assert refreshed.receipt_id != receipt.receipt_id
    wrapped = [item for item in pack.build_live_adapters() if item.adapter_id == adapter.adapter_id][0]
    assert asyncio.run(wrapped.health())["ok"] is True

    binary.write_text(binary.read_text(encoding="utf-8") + "\n# changed binary\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    stale = asyncio.run(wrapped.health())
    assert stale["ok"] is False
    assert stale["conformance_state"] == RuntimeConformanceState.STALE.value


def test_conformance_ledger_is_append_only(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    binary = _fake_opencode(tmp_path / "opencode")
    key = tmp_path / "zen.key"; key.write_text("fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(binary))
    monkeypatch.setenv("AETHER_OPENCODE_API_KEY_FILE", str(key))
    pack = RuntimeDriverPack(tmp_path / "drivers", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"), allowed_workspace_roots=[root])
    receipt = asyncio.run(pack.conform("opencode-cli", principal="founder"))
    from datetime import datetime, timedelta, timezone
    status = {item.manifest.driver_id: item for item in pack.status()}["opencode-cli"]
    state, _, _ = pack.conformance_store.validate(
        status.manifest,
        executable_path=str(Path(status.executable).resolve()),
        executable_sha256=status.metadata["executable_sha256"],
        runtime_version=status.runtime_version,
        configuration_hash=status.metadata["configuration_hash"],
        now=datetime.now(timezone.utc) + timedelta(days=2),
    )
    assert state == RuntimeConformanceState.EXPIRED
    conn = sqlite3.connect(pack.conformance_store.path)
    try:
        try:
            conn.execute("UPDATE runtime_conformance_receipts SET issued_by = 'model' WHERE receipt_id = ?", (receipt.receipt_id,))
        except sqlite3.DatabaseError:
            pass
        else:
            raise AssertionError("append-only conformance ledger accepted UPDATE")
    finally:
        conn.close()


def test_reliability_penalty_ranks_healthy_codex_ahead_of_failing_opencode(tmp_path: Path, monkeypatch):
    from aether_gateway.runtime_sdk import RuntimeAdapterRegistry
    from test_codex_cli_driver import _fake_codex

    root = _workspace(tmp_path)
    open_binary = _fake_opencode(tmp_path / "opencode")
    codex_binary = _fake_codex(tmp_path / "codex")
    key = tmp_path / "zen.key"; key.write_text("fixture-secret\n", encoding="utf-8")
    monkeypatch.setenv("AETHER_OPENCODE_BIN", str(open_binary))
    monkeypatch.setenv("AETHER_OPENCODE_API_KEY_FILE", str(key))
    monkeypatch.setenv("AETHER_CODEX_BIN", str(codex_binary))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-credential")
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    for index in range(3):
        telemetry.record_invocation(
            task_id=f"open-fail-{index}", adapter_id="runtime.coding.opencode-cli", workspace_id="w1", session_id="s1",
            ok=False, status="failed", duration_seconds=2.0, artifact_count=0, verification_count=0,
            failure_fingerprint=f"f{index}", payload={},
        )
        telemetry.record_invocation(
            task_id=f"codex-ok-{index}", adapter_id="runtime.coding.openai-codex-cli", workspace_id="w1", session_id="s1",
            ok=True, status="completed", duration_seconds=1.0, artifact_count=1, verification_count=1,
            failure_fingerprint=None, payload={},
        )
    pack = RuntimeDriverPack(tmp_path / "drivers", telemetry, allowed_workspace_roots=[root])
    asyncio.run(pack.conform("opencode-cli", principal="founder"))
    asyncio.run(pack.conform("openai-codex-cli", principal="founder"))
    registry = RuntimeAdapterRegistry()
    for adapter in pack.build_live_adapters():
        registry.register(adapter, adapter.descriptor)
    descriptors = asyncio.run(registry.discover())
    live = [item for item in descriptors if item.adapter_id in {"runtime.coding.opencode-cli", "runtime.coding.openai-codex-cli"}]
    assert [item.adapter_id for item in live][:2] == ["runtime.coding.openai-codex-cli", "runtime.coding.opencode-cli"]
    assert live[0].metadata["reliability_score"] > live[1].metadata["reliability_score"]
