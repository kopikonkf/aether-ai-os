from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

from aether.contracts import RuntimeCommand
from aether_gateway.runtime_sdk import (
    ExternalStreamingCodingRuntimeAdapter,
    RuntimeAdapterRegistry,
    RuntimeTelemetryStore,
)


def _binding(root: Path):
    return {
        "workspace_id": "workspace-1",
        "root_path": str(root),
        "session_id": "session-1",
        "allowed_relative_paths": ["."],
        "writable": True,
    }


def _task(root: Path, *, task_id: str, content: str, verify: str = "test_calc.py"):
    before = (root / "calc.py").read_bytes()
    return {
        "task_id": task_id,
        "objective": "Correct the addition implementation.",
        "workspace_id": "workspace-1",
        "session_id": "session-1",
        "edits": [{
            "path": "calc.py",
            "content": content,
            "expected_sha256": hashlib.sha256(before).hexdigest(),
        }],
        "verification_commands": [{
            "argv": [sys.executable, "-m", "pytest", "-q", verify],
            "label": "heldout",
        }],
        "max_artifacts": 10,
        "max_total_bytes": 262144,
    }


def _workspace(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    return root


def _reference_adapter(tmp_path: Path, root: Path):
    return ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, "-m", "aether_gateway.runtime_sdk.reference_external_runtime"),
        tmp_path / "state",
        RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
    )


def test_external_runtime_handshake_updates_discovery(tmp_path: Path):
    root = _workspace(tmp_path)
    adapter = _reference_adapter(tmp_path, root)
    registry = RuntimeAdapterRegistry()
    registry.register(adapter, adapter.descriptor)
    descriptors = asyncio.run(registry.discover())
    assert len(descriptors) == 1
    descriptor = descriptors[0]
    assert descriptor.health_status.value == "healthy"
    assert descriptor.metadata["runtime_version"] == "0.1.0"
    assert "jsonl-stream-v1" in descriptor.runtime_features
    assert descriptor.metadata["health"]["protocol"] == "aether.coding-jsonl.v1"


def test_external_runtime_streams_patch_verifies_and_applies(tmp_path: Path):
    root = _workspace(tmp_path)
    adapter = _reference_adapter(tmp_path, root)
    result = asyncio.run(adapter.execute(RuntimeCommand(
        "coding.task.execute",
        {"task": _task(root, task_id="task-success", content="def add(a, b):\n    return a + b\n"), "workspace_binding": _binding(root)},
    )))
    assert result.ok is True, result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    assert result.metadata["patch_trusted"] is False
    assert result.metadata["independent_verification"] is True
    assert result.metadata["runtime_frame_count"] >= 5
    assert result.output["artifacts"][0]["path"] == "calc.py"
    assert result.output["metadata"]["external_runtime_version"] == "0.1.0"
    transcript = tmp_path / "state" / "runs" / "task-success" / "stream.jsonl"
    assert transcript.exists()
    assert "artifact.patch" in transcript.read_text(encoding="utf-8")


def test_failed_independent_verification_leaves_production_unchanged(tmp_path: Path):
    root = _workspace(tmp_path)
    original = (root / "calc.py").read_text(encoding="utf-8")
    adapter = _reference_adapter(tmp_path, root)
    result = asyncio.run(adapter.execute(RuntimeCommand(
        "coding.task.execute",
        {"task": _task(root, task_id="task-bad", content="def add(a, b):\n    return 999\n"), "workspace_binding": _binding(root)},
    )))
    assert result.ok is False
    assert "independent verification failed" in result.error
    assert (root / "calc.py").read_text(encoding="utf-8") == original


def _write_runtime_script(path: Path, run_body: str):
    path.write_text(
        "import json,sys\n"
        "P='aether.coding-jsonl.v1'\n"
        "if '--aether-handshake' in sys.argv:\n"
        " print(json.dumps({'protocol':P,'runtime':{'id':'test.external','version':'1','display_name':'Test','operations':['coding.task.execute'],'capabilities':['coding.edit'],'features':['jsonl-stream-v1']},'limits':{'max_frame_bytes':65536,'max_patch_files':10}})); raise SystemExit(0)\n"
        "req=json.loads(sys.stdin.readline()); task=req['task']; tid=task['task_id']\n"
        + run_body,
        encoding="utf-8",
    )


def test_out_of_order_stream_is_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    script = tmp_path / "bad_runtime.py"
    _write_runtime_script(script,
        "print(json.dumps({'type':'task.accepted','protocol':P,'task_id':tid,'sequence':2,'payload':{}}),flush=True)\n"
        "print(json.dumps({'type':'task.completed','protocol':P,'task_id':tid,'sequence':1,'payload':{'ok':True}}),flush=True)\n"
    )
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, str(script)), tmp_path / "state", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
    )
    result = asyncio.run(adapter.execute(RuntimeCommand(
        "coding.task.execute",
        {"task": _task(root, task_id="task-order", content="def add(a,b):\n return a+b\n"), "workspace_binding": _binding(root)},
    )))
    assert result.ok is False
    assert "sequence" in result.error
    assert (root / "calc.py").read_text(encoding="utf-8").endswith("return a - b\n")


def test_external_process_does_not_inherit_operator_secret(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    script = tmp_path / "secret_runtime.py"
    _write_runtime_script(script,
        "import os\n"
        "if os.environ.get('AETHER_OPERATOR_TOKEN'):\n"
        " print(json.dumps({'type':'task.error','protocol':P,'task_id':tid,'sequence':1,'payload':{'error':'secret leaked'}}),flush=True)\n"
        "else:\n"
        " print(json.dumps({'type':'task.error','protocol':P,'task_id':tid,'sequence':1,'payload':{'error':'secret absent'}}),flush=True)\n"
    )
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "must-not-leak")
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, str(script)), tmp_path / "state", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
    )
    result = asyncio.run(adapter.execute(RuntimeCommand(
        "coding.task.execute",
        {"task": _task(root, task_id="task-secret", content="def add(a,b):\n return a+b\n"), "workspace_binding": _binding(root)},
    )))
    assert result.ok is False
    assert "secret absent" in result.error
    assert "secret leaked" not in result.error


def test_runtime_patch_hash_mismatch_is_rejected(tmp_path: Path):
    root = _workspace(tmp_path)
    original = (root / "calc.py").read_text(encoding="utf-8")
    script = tmp_path / "mismatch_runtime.py"
    _write_runtime_script(script,
        "print(json.dumps({'type':'task.accepted','protocol':P,'task_id':tid,'sequence':1,'payload':{}}),flush=True)\n"
        "print(json.dumps({'type':'artifact.patch','protocol':P,'task_id':tid,'sequence':2,'payload':{'path':'calc.py','kind':'upsert','before_sha256':'0'*64,'content':'def add(a,b):\\n return a+b\\n'}}),flush=True)\n"
        "print(json.dumps({'type':'task.completed','protocol':P,'task_id':tid,'sequence':3,'payload':{'ok':True}}),flush=True)\n"
    )
    adapter = ExternalStreamingCodingRuntimeAdapter(
        (sys.executable, str(script)), tmp_path / "state", RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3"),
        allowed_workspace_roots=[root],
    )
    result = asyncio.run(adapter.execute(RuntimeCommand(
        "coding.task.execute",
        {"task": _task(root, task_id="task-mismatch", content="def add(a,b):\n return a+b\n"), "workspace_binding": _binding(root)},
    )))
    assert result.ok is False
    assert "before_sha256 mismatch" in result.error
    assert (root / "calc.py").read_text(encoding="utf-8") == original
