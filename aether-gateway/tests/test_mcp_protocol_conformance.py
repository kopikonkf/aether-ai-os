from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_aether_mcp_stdio_conformance(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project.mkdir()
    (project / "RELEASE_BUILD.json").write_text(
        '{"release":"0.19.2","build_id":"mcp-conformance","status":"test"}',
        encoding="utf-8",
    )
    (project / "LASTSTANDINGPOINT.md").write_text(
        "# MCP conformance\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env.update({
        "AETHER_PROJECT_ROOT": str(project),
        "AETHER_HOME": str(home),
    })
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "aether_gateway.mcp.server", "--transport", "stdio"],
        env=env,
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
            status = await session.call_tool("aether_status", arguments={})

    tool_names = {item.name for item in tools.tools}
    resource_uris = {str(item.uri) for item in resources.resources}
    prompt_names = {item.name for item in prompts.prompts}
    assert tool_names == {
        "aether_status",
        "aether_capability_manifest",
        "aether_handoff",
        "memory_search",
        "artifact_hash_verify",
    }
    assert resource_uris == {
        "aether://status",
        "aether://capabilities",
        "aether://handoff",
    }
    assert prompt_names == {"aether_operational_context"}
    assert bool(
        getattr(status, "isError", getattr(status, "is_error", False))
    ) is False
    assert not home.exists(), "stdio conformance must not create AETHER_HOME"
