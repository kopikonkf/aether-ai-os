import json
from pathlib import Path

from aether.runtime.mcp import (
    AetherMcpActivation,
    AetherMcpConfig,
    AetherMcpJsonRpcServer,
    REQUIRED_AETHER_MCP_TOOLS,
)


class FakeMcpMind:
    def __init__(self, alive=True):
        self.alive = alive
        self.calls = []

    def is_alive(self):
        return self.alive

    def who_am_i(self):
        self.calls.append(("who_am_i", {}))
        return {"name": "Aether", "alive": True, "narrative": "mind online"}

    def north_star_evaluate(self, payload):
        self.calls.append(("north_star_evaluate", dict(payload)))
        return {"approved": True, "alignment_score": 0.95, "warnings": [], "escalate_to_dee": False}

    def believe(self, payload):
        self.calls.append(("believe", dict(payload)))
        return {"accepted": True, "claim": payload["claim"], "note": "queued_no_consciousness"}

    def run_task(self, payload):
        self.calls.append(("run_task", dict(payload)))
        return {"accepted": True, "task_id": "task-1", "note": "queued"}


def make_activation(tmp_path: Path, mind: FakeMcpMind) -> AetherMcpActivation:
    return AetherMcpActivation(
        AetherMcpConfig(aether_home=tmp_path, mind_url="http://127.0.0.1:8765"),
        mind_client=mind,
    )


def test_activate_writes_manifest_and_receipt(tmp_path):
    activation = make_activation(tmp_path, FakeMcpMind())

    record = activation.activate()

    assert record["activated"] is True
    assert set(REQUIRED_AETHER_MCP_TOOLS).issubset(set(record["tools"]))
    assert (tmp_path / "runtime" / "mcp" / "manifest.json").exists()
    assert "mcp.activation.completed" in (tmp_path / "runtime" / "mcp" / "receipts.jsonl").read_text(
        encoding="utf-8"
    )


def test_tool_call_refuses_when_mind_down(tmp_path):
    activation = make_activation(tmp_path, FakeMcpMind(alive=False))
    activation.activate()

    result = activation.call_tool("aether_who_am_i")

    assert result["ok"] is False
    assert result["status"] == "fail_safe"
    assert result["reason"] == "mind_unreachable_fail_safe"
    assert "mcp.tool.refused" in (tmp_path / "runtime" / "mcp" / "receipts.jsonl").read_text(
        encoding="utf-8"
    )


def test_run_task_tool_calls_mind_and_receipts(tmp_path):
    mind = FakeMcpMind(alive=True)
    activation = make_activation(tmp_path, mind)
    activation.activate()

    result = activation.call_tool(
        "aether_run_task",
        {"goal": "Inspect MCP activation.", "context": {"source": "test"}},
    )

    assert result["ok"] is True
    assert result["result"]["accepted"] is True
    assert mind.calls[-1][0] == "run_task"
    assert mind.calls[-1][1]["goal"] == "Inspect MCP activation."
    assert "mcp.tool.completed" in (tmp_path / "runtime" / "mcp" / "receipts.jsonl").read_text(
        encoding="utf-8"
    )


def test_json_rpc_initialize_list_and_call(tmp_path):
    activation = make_activation(tmp_path, FakeMcpMind(alive=True))
    server = AetherMcpJsonRpcServer(activation)

    init_response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    list_response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    call_response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "aether_who_am_i", "arguments": {}},
        }
    )

    assert init_response["result"]["activation"]["activated"] is True
    names = {tool["name"] for tool in list_response["result"]["tools"]}
    assert set(REQUIRED_AETHER_MCP_TOOLS).issubset(names)
    payload = json.loads(call_response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["result"]["name"] == "Aether"
