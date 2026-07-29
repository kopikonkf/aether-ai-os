from __future__ import annotations

import asyncio
import importlib
import sys

from fastapi.testclient import TestClient


def test_knowledge_api_requires_trusted_review_and_promotes_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "knowledge-api-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")

    from aether.contracts import MemoryKind, MemoryProvenance, MemoryRecord

    async def seed():
        first = await server.memory_fabric.remember(MemoryRecord(
            key="knowledge-api-e1",
            value="runtime adapter replacement test A passed",
            namespace="episodes",
            kind=MemoryKind.OBSERVATION,
            content="Runtime adapter replacement test A passed without Core changes.",
            provenance=MemoryProvenance("test:a", "2026-07-28T00:00:01Z"),
        ))
        second = await server.memory_fabric.remember(MemoryRecord(
            key="knowledge-api-e2",
            value="runtime adapter replacement test B passed",
            namespace="episodes",
            kind=MemoryKind.OBSERVATION,
            content="Runtime adapter replacement test B passed without Core changes.",
            provenance=MemoryProvenance("test:b", "2026-07-28T00:00:02Z"),
        ))
        return first, second

    first, second = asyncio.run(seed())
    headers = {"X-Aether-Operator-Token": "knowledge-api-secret"}
    with TestClient(server.app) as client:
        unauthorized = client.get("/api/knowledge/proposals")
        assert unauthorized.status_code == 401

        proposed = client.post(
            "/api/knowledge/proposals",
            headers=headers,
            json={
                "claim": "Runtime adapters are replaceable without Core changes.",
                "claim_key": "architecture.runtime-adapters",
                "polarity": 1,
                "evidence_record_ids": [first.record_id, second.record_id],
            },
        )
        assert proposed.status_code == 200
        body = proposed.json()
        assert body["status"] == "proposed"
        assert body["blockers"] == []
        proposal_id = body["proposal_id"]

        promoted = client.post(
            f"/api/knowledge/proposals/{proposal_id}/approve",
            headers=headers,
            json={"reason": "Two independent adapter replacement tests passed.", "confidence": 0.8},
        )
        assert promoted.status_code == 200
        promoted_body = promoted.json()
        assert promoted_body["status"] == "promoted"
        assert promoted_body["decision"]["principal"] == "founder"
        assert promoted_body["knowledge_record_id"].startswith("knowledge.")

        knowledge = client.get("/api/knowledge", headers=headers)
        assert knowledge.status_code == 200
        assert knowledge.json()["knowledge"][0]["claim"].startswith("Runtime adapters")
        assert set(knowledge.json()["knowledge"][0]["evidence_links"]) == {first.record_id, second.record_id}

        projected = client.post(f"/api/knowledge/project/{proposal_id}", headers=headers)
        assert projected.status_code == 200
        assert projected.json()["path"].endswith(".md")
