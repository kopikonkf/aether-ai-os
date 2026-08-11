from __future__ import annotations

from pathlib import Path

import pytest

from aether_gateway.mcp.living_machine import LivingMachineMCPService, LivingMachinePolicyError


class FakeBindings:
    def __init__(self, binding):
        self.binding = binding

    def list_bindings(self, *, limit=1000):
        return (self.binding,)

    def resolve(self, workspace_id, session_id):
        if workspace_id != self.binding.workspace_id or session_id != self.binding.session_id:
            raise RuntimeError("binding mismatch")
        return self.binding


class FakeTelemetry:
    def status(self):
        return {"invocations": 0, "progress_events": 0}

    def list_invocations(self, *, limit=100):
        return ()


class FakeRegistry:
    async def discover(self):
        return ()


class FakeActionPath:
    async def execute(self, proposal, approval):
        return {"ok": True, "proposal": proposal.action_id}


class Binding:
    workspace_id = "ws-1"
    binding_id = "binding-1"
    root_path = ""
    session_id = "session-1"
    allowed_relative_paths = (".",)
    writable = True
    metadata = {}


def service(tmp_path: Path) -> LivingMachineMCPService:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.txt").write_text("hello\nworld\n", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=value\n", encoding="utf-8")
    Binding.root_path = str(workspace)
    return LivingMachineMCPService(
        project_root=tmp_path,
        aether_home=tmp_path / "home",
        workspace_roots=(workspace,),
        workspace_bindings=FakeBindings(Binding()),
        runtime_registry=FakeRegistry(),
        runtime_telemetry=FakeTelemetry(),
        action_path=FakeActionPath(),
    )


def test_read_allowed_file_and_hash(tmp_path):
    svc = service(tmp_path)
    result = svc.file_read("workspace/safe.txt")
    assert result["content"] == "hello\nworld"
    assert len(result["sha256"]) == 64


def test_path_traversal_denied(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(LivingMachinePolicyError):
        svc.file_read("workspace/../home/secret.txt")


def test_secret_path_denied(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(LivingMachinePolicyError):
        svc.file_read("workspace/.env")


def test_operator_token_is_required_for_mutation(tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setenv("AETHER_MCP_OPERATOR_TOKEN", "operator-secret")
    with pytest.raises(LivingMachinePolicyError):
        import asyncio
        asyncio.run(svc.workspace_edit(
            workspace_id="ws-1",
            session_id="session-1",
            edits=[{"path": "safe.txt", "content": "changed", "expected_sha256": None}],
            verification_commands=[],
            reason="test",
            operator="test",
            operator_token="wrong",
        ))


def test_git_is_read_only_surface(tmp_path):
    svc = service(tmp_path)
    result = svc.capability_manifest()
    assert "git_status" in result["tools"]
    assert result["shell"] is False
    assert result["secrets"] is False
