from __future__ import annotations

import asyncio
from pathlib import Path

from aether.contracts import RuntimeCommand
from aether_gateway.actions import RegistryToolExecutor
from aether_gateway.adapters import LocalProcessRuntimeAdapter
from aether_tools import ToolRegistry
from aether_tools.primitives import ReadTool


def test_registry_tool_executor_reads_bounded_file(tmp_path: Path):
    target = tmp_path / "evidence.txt"
    target.write_text("verified", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadTool([tmp_path]))
    executor = RegistryToolExecutor(registry)
    result = asyncio.run(executor.execute_tool("read", {"path": "evidence.txt"}))
    assert result.ok and "verified" in result.output
    capabilities = asyncio.run(executor.capabilities())
    assert capabilities[0].operation == "read"


def test_local_process_runtime_executes_only_allowlisted_echo(tmp_path: Path):
    runtime = LocalProcessRuntimeAdapter(cwd=tmp_path)
    ok = asyncio.run(runtime.execute(RuntimeCommand("echo", {"text": "body online"})))
    denied = asyncio.run(runtime.execute(RuntimeCommand("shell", {"text": "no"})))
    assert ok.ok and ok.output == "body online" and ok.metadata["shell"] is False
    assert not denied.ok and denied.metadata["error_type"] == "CommandDenied"
