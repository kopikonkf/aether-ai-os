from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from aether.contracts import RuntimeCommand
from aether_gateway.runtime_sdk import (
    LocalStructuredCodingRuntimeAdapter, RuntimeAdapterRegistry, RuntimeTelemetryStore,
    SQLiteWorkspaceBindingStore, WorkspaceBindingError,
)


def make_command(workspace: Path, *, content: str, expected: str | None, verification=None, task_id="coding-task-1"):
    return RuntimeCommand(
        "coding.task.execute",
        {
            "task": {
                "task_id": task_id,
                "objective": "Fix the bounded source file.",
                "workspace_id": "workspace-1",
                "session_id": "session-1",
                "edits": [{"path": "calc.py", "content": content, "expected_sha256": expected}],
                "verification_commands": verification or [
                    {"argv": ["python", "-m", "compileall", "calc.py"], "label": "compile"}
                ],
                "max_artifacts": 5,
                "max_total_bytes": 10000,
            },
            "workspace_binding": {
                "workspace_id": "workspace-1",
                "root_path": str(workspace),
                "session_id": "session-1",
                "allowed_relative_paths": ["."],
                "writable": True,
            },
        },
        correlation_id="corr-1",
    )


def test_workspace_binding_is_immutable_and_session_bound(tmp_path: Path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    store = SQLiteWorkspaceBindingStore(tmp_path / "bindings.sqlite3", [allowed])
    binding = store.bind(allowed, "session-1", workspace_id="workspace-1")
    assert store.resolve("workspace-1", "session-1") == binding
    with pytest.raises(WorkspaceBindingError):
        store.resolve("workspace-1", "other-session")
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(WorkspaceBindingError):
        store.bind(outside, "session-1")


def test_registry_discovers_health_and_capabilities(tmp_path: Path):
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    runtime = LocalStructuredCodingRuntimeAdapter(tmp_path / "state", telemetry, allowed_workspace_roots=[tmp_path])
    registry = RuntimeAdapterRegistry()
    registry.register(runtime, runtime.descriptor)
    descriptors = asyncio.run(registry.discover())
    assert descriptors[0].health_status.value == "healthy"
    assert "coding.edit" in descriptors[0].capabilities
    assert registry.runtime_mapping()[runtime.routing_key] is runtime


def test_local_coding_runtime_applies_verifies_and_returns_bounded_artifact(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = "def add(a, b):\n    return a - b\n"
    target = workspace / "calc.py"
    target.write_text(original, encoding="utf-8")
    expected = hashlib.sha256(original.encode()).hexdigest()
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    runtime = LocalStructuredCodingRuntimeAdapter(tmp_path / "state", telemetry, allowed_workspace_roots=[tmp_path])
    result = asyncio.run(runtime.execute(make_command(
        workspace, content="def add(a, b):\n    return a + b\n", expected=expected,
    )))
    assert result.ok is True, result.error
    assert "return a + b" in target.read_text()
    artifact = result.output["artifacts"][0]
    assert artifact["path"] == "calc.py"
    assert artifact["before_sha256"] == expected
    assert artifact["after_sha256"] != expected
    assert "-    return a - b" in artifact["diff"]
    assert result.metadata["result_verified"] is True
    assert telemetry.status()["invocations"] == 1
    assert telemetry.status()["progress_events"] >= 4


def test_verification_failure_rolls_back_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    original = "value = 1\n"
    target = workspace / "calc.py"
    target.write_text(original, encoding="utf-8")
    expected = hashlib.sha256(original.encode()).hexdigest()
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    runtime = LocalStructuredCodingRuntimeAdapter(tmp_path / "state", telemetry, allowed_workspace_roots=[tmp_path])
    result = asyncio.run(runtime.execute(make_command(
        workspace,
        content="value = 2\n",
        expected=expected,
        verification=[{"argv": ["python", "-m", "unittest", "missing_module"], "label": "must-fail"}],
    )))
    assert result.ok is False
    assert result.metadata["rollback_performed"] is True
    assert target.read_text(encoding="utf-8") == original


def test_runtime_denies_traversal_and_unallowlisted_command(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    runtime = LocalStructuredCodingRuntimeAdapter(tmp_path / "state", telemetry, allowed_workspace_roots=[tmp_path])
    traversal = make_command(workspace, content="bad", expected=None)
    traversal.arguments["task"]["edits"][0]["path"] = "../escape.py"
    result = asyncio.run(runtime.execute(traversal))
    assert result.ok is False
    assert not (tmp_path / "escape.py").exists()

    denied = make_command(workspace, content="value=1\n", expected=None,
                          verification=[{"argv": ["bash", "-lc", "echo unsafe"], "label": "unsafe"}],
                          task_id="coding-task-2")
    result = asyncio.run(runtime.execute(denied))
    assert result.ok is False
    assert not (workspace / "calc.py").exists()


def test_registry_rejects_nonconforming_descriptor(tmp_path: Path):
    from dataclasses import replace
    from aether_gateway.runtime_sdk import RuntimeAdapterConformanceError

    telemetry = RuntimeTelemetryStore(tmp_path / "telemetry.sqlite3")
    runtime = LocalStructuredCodingRuntimeAdapter(tmp_path / "state", telemetry, allowed_workspace_roots=[tmp_path])
    registry = RuntimeAdapterRegistry()
    with pytest.raises(RuntimeAdapterConformanceError):
        registry.register(runtime, replace(runtime.descriptor, operations=("unsafe.execute",)))


def test_private_dispatcher_falls_back_after_approved_runtime_failure(tmp_path: Path):
    from aether.contracts import RuntimeResult
    from aether.contracts.coding_runtime import RuntimeDescriptor, RuntimeHealthStatus
    from aether_gateway.runtime_sdk import CodingRuntimeDispatchAdapter

    class StubRuntime:
        def __init__(self, adapter_id: str, routing_key: str, ok: bool):
            self._adapter_id = adapter_id
            self.routing_key = routing_key
            self.ok = ok

        @property
        def adapter_id(self):
            return self._adapter_id

        @property
        def descriptor(self):
            return RuntimeDescriptor(
                routing_key=self.routing_key,
                adapter_id=self.adapter_id,
                display_name=self.adapter_id,
                operations=("coding.task.execute",),
                capabilities=("coding.edit",),
                runtime_features=("structured-edits",),
                health_status=RuntimeHealthStatus.HEALTHY,
            )

        async def capabilities(self):
            return {"coding.task.execute"}

        async def health(self):
            return {"ok": True}

        async def execute(self, command):
            if self.ok:
                return RuntimeResult(True, output={"runtime": self.adapter_id}, metadata={"result_verified": True})
            return RuntimeResult(False, error=f"{self.adapter_id} failed", metadata={"failure_fingerprint": f"fp-{self.adapter_id}"})

    registry = RuntimeAdapterRegistry()
    first = StubRuntime("runtime.first", "runtime://first", False)
    second = StubRuntime("runtime.second", "runtime://second", True)
    registry.register(first, first.descriptor)
    registry.register(second, second.descriptor)
    dispatcher = CodingRuntimeDispatchAdapter(registry)
    result = asyncio.run(dispatcher.execute(RuntimeCommand(
        "coding.task.execute",
        {
            "task": {"task_id": "task-1"},
            "workspace_binding": {},
            "runtime_candidates": [
                {"routing_key": first.routing_key, "adapter_id": first.adapter_id},
                {"routing_key": second.routing_key, "adapter_id": second.adapter_id},
            ],
        },
    )))
    assert result.ok is True
    assert result.output == {"runtime": "runtime.second"}
    assert result.metadata["fallback_used"] is True
    assert result.metadata["selected_runtime_adapter_id"] == "runtime.second"
    assert len(result.metadata["runtime_attempts"]) == 2
