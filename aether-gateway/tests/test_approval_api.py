from __future__ import annotations

import asyncio
import importlib
import sys

from fastapi.testclient import TestClient

from aether.contracts import ActionProposal, ActionRisk, ActionScope, ActionTarget


def test_approval_api_requires_operator_and_blocks_replay(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "api-test-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")

    proposal = ActionProposal(
        target=ActionTarget.TOOL,
        operation="write",
        arguments={"path": "api-test.txt", "_body": "verified\n"},
        required_scopes=(ActionScope.WRITE,),
        reason="Verify trusted approval API",
        risk=ActionRisk.MEDIUM,
        reversible=False,
        metadata={"channel": "http", "session_id": "http:api-test"},
    )
    pending = asyncio.run(server.action_path.execute(proposal))
    approval_id = str(pending.metadata["approval_id"])

    with TestClient(server.app) as client:
        assert client.get("/api/approvals").status_code == 401
        status = client.get("/api/approvals/status")
        assert status.status_code == 200 and status.json()["pending"] == 1
        headers = {"X-Aether-Operator-Token": "api-test-secret"}
        listed = client.get("/api/approvals", headers=headers)
        assert listed.status_code == 200
        approval = listed.json()["approvals"][0]
        assert approval["approval_id"] == approval_id
        action_hash = approval["action_hash"]

        mismatch = client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=headers,
            json={"reason": "Reject stale operator view", "expected_action_hash": "0" * 64},
        )
        assert mismatch.status_code == 409
        assert "does not match" in mismatch.json()["detail"]
        assert not (tmp_path / "home" / "api-test.txt").exists()
        assert client.get("/api/approvals", headers=headers).json()["approvals"][0]["status"] == "pending"

        approved = client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=headers,
            json={"reason": "Exact payload reviewed", "expected_action_hash": action_hash},
        )
        assert approved.status_code == 200
        assert approved.json()["approval"]["status"] == "consumed"

        replay = client.post(
            f"/api/approvals/{approval_id}/approve",
            headers=headers,
            json={"reason": "Duplicate HTTP request", "expected_action_hash": action_hash},
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

    assert (tmp_path / "home" / "api-test.txt").read_text(encoding="utf-8") == "verified\n"
