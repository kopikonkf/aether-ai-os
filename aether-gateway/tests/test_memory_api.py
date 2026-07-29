from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def test_memory_api_persists_searches_rebuilds_and_projects(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AETHER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AETHER_OPERATOR_TOKEN", "memory-api-secret")
    monkeypatch.setenv("AETHER_OPERATOR_ID", "founder")
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    sys.modules.pop("aether_gateway.api.server", None)
    server = importlib.import_module("aether_gateway.api.server")

    with TestClient(server.app) as client:
        chat = client.post("/api/chat", json={"message": "Remember modular architecture", "session_id": "http:memory-api"})
        # Live provider may not have credentials in tests, so seed through the fabric directly below.
        assert chat.status_code in {200, 502}

        import asyncio
        from aether.contracts import MemoryKind, MemoryProvenance, MemoryRecord
        asyncio.run(server.memory_fabric.remember(MemoryRecord(
            key="api-memory",
            value="modular architecture",
            namespace="episodes",
            kind=MemoryKind.OBSERVATION,
            content="Aether uses modular runtime agnostic architecture.",
            provenance=MemoryProvenance("test", "2026-07-28T00:00:00Z", session_id="http:memory-api"),
        )))

        found = client.post("/api/memory/search", json={"query": "modular architecture", "namespaces": ["episodes"]})
        assert found.status_code == 200
        assert found.json()["hits"][0]["provenance"]["source"] == "test"

        assert client.post("/api/memory/rebuild").status_code == 401
        headers = {"X-Aether-Operator-Token": "memory-api-secret"}
        rebuilt = client.post("/api/memory/rebuild", headers=headers)
        assert rebuilt.status_code == 200 and rebuilt.json()["records"] >= 1

        projected = client.post("/api/memory/project/http:memory-api", headers=headers)
        assert projected.status_code == 200
        assert projected.json()["path"].endswith("http-memory-api.md")

        sessions = client.get("/api/sessions")
        assert sessions.status_code == 200
