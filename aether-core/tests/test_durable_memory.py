from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from aether.cognition import AetherCognitiveGateway, SQLiteConversationStore
from aether.contracts import MemoryKind, MemoryProvenance, MemoryQuery, MemoryRecord, ModelResponse, Perception
from aether.events import EventBus
from aether.memory import AetherMemoryFabric, ObsidianMemoryProjector, SQLiteCanonicalMemoryStore, SQLiteLexicalMemoryProvider


def _fabric(tmp_path: Path):
    canonical = SQLiteCanonicalMemoryStore(tmp_path / "canonical.sqlite3")
    retrieval = SQLiteLexicalMemoryProvider(tmp_path / "index.sqlite3", canonical)
    fabric = AetherMemoryFabric(
        canonical,
        retrieval,
        event_bus=EventBus(tmp_path / "memory-events.jsonl"),
        obsidian=ObsidianMemoryProjector(tmp_path / "vault"),
    )
    return canonical, retrieval, fabric


def test_sqlite_conversation_store_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "sessions.sqlite3"

    async def scenario():
        first = SQLiteConversationStore(path, max_messages=4)
        await first.append("telegram:1", {"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"})
        second = SQLiteConversationStore(path, max_messages=4)
        return await second.get("telegram:1")

    messages = asyncio.run(scenario())
    assert [item["content"] for item in messages] == ["hello", "hi"]


def test_canonical_memory_is_append_only_and_index_is_rebuildable(tmp_path: Path) -> None:
    canonical, retrieval, fabric = _fabric(tmp_path)

    async def scenario():
        record = await fabric.remember(MemoryRecord(
            key="architecture-preference",
            value={"preference": "modular runtime agnostic architecture"},
            namespace="episodes",
            kind=MemoryKind.OBSERVATION,
            content="Founder prefers modular runtime agnostic architecture.",
            provenance=MemoryProvenance("founder:telegram", "2026-07-28T00:00:00Z", session_id="telegram:1"),
        ))
        before = await fabric.retrieve(MemoryQuery("modular architecture", namespaces=("episodes",), limit=5))
        rebuilt = await fabric.rebuild_index()
        after = await fabric.retrieve(MemoryQuery("runtime agnostic", namespaces=("episodes",), limit=5))
        return record, before, rebuilt, after

    record, before, rebuilt, after = asyncio.run(scenario())
    assert record.record_id and record.content_hash
    assert before.hits[0].record.record_id == record.record_id
    assert rebuilt == 1
    assert after.hits[0].record.content_hash == record.content_hash

    with sqlite3.connect(canonical.path) as conn:
        try:
            conn.execute("UPDATE memory_records SET content='tampered' WHERE record_id=?", (record.record_id,))
        except sqlite3.DatabaseError as exc:
            assert "append-only" in str(exc)
        else:
            raise AssertionError("canonical memory update should be rejected")


class MemoryAwareProvider:
    provider_id = "provider.memory-aware"

    def __init__(self):
        self.requests = []

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request):
        self.requests.append(request)
        context = "\n".join(str(item.get("content", "")) for item in request.messages)
        answer = "The architecture preference is modular and runtime agnostic." if "modular runtime agnostic" in context else "No memory found."
        return ModelResponse(answer, self.provider_id, "memory-v1")


def test_gateway_retrieves_provenance_before_cognition_and_records_turn(tmp_path: Path) -> None:
    canonical, _retrieval, fabric = _fabric(tmp_path)
    provider = MemoryAwareProvider()
    session_path = tmp_path / "sessions.sqlite3"

    async def scenario():
        await fabric.remember(MemoryRecord(
            key="founder-architecture",
            value="modular runtime agnostic architecture",
            namespace="episodes",
            kind=MemoryKind.OBSERVATION,
            content="Founder chose modular runtime agnostic architecture.",
            provenance=MemoryProvenance("founder", "2026-07-28T00:00:00Z", session_id="telegram:founder"),
        ))
        gateway = AetherCognitiveGateway(
            provider,
            conversation_store=SQLiteConversationStore(session_path),
            memory_fabric=fabric,
        )
        expression = await gateway.respond(Perception(
            "telegram.text",
            "What architecture preference was chosen?",
            "telegram:founder",
            metadata={"session_id": "telegram:founder", "channel": "telegram"},
            correlation_id="corr-memory-1",
        ))
        restarted = SQLiteConversationStore(session_path)
        return expression, await restarted.get("telegram:founder"), await canonical.count()

    expression, messages, count = asyncio.run(scenario())
    assert expression.content.startswith("The architecture preference")
    assert expression.metadata["memory_retrieval"]["hit_count"] == 1
    assert "Retrieved Aether memory" in provider.requests[0].messages[0]["content"]
    assert "content_hash" in provider.requests[0].messages[0]["content"]
    assert len(messages) == 2
    assert count == 2  # seeded knowledge + canonical interaction episode


def test_obsidian_projection_is_explicit_and_rebuildable(tmp_path: Path) -> None:
    _canonical, _retrieval, fabric = _fabric(tmp_path)

    async def scenario():
        await fabric.remember(MemoryRecord(
            key="turn-1",
            value="hello",
            namespace="episodes",
            kind=MemoryKind.EPISODE,
            content="User: hello\nAether: hi",
            provenance=MemoryProvenance("telegram:1", "2026-07-28T00:00:00Z", session_id="telegram:1"),
        ))
        return await fabric.project_session("telegram:1")

    path = Path(asyncio.run(scenario()))
    text = path.read_text(encoding="utf-8")
    assert "authority: projection_only" in text
    assert "Canonical memory remains in Aether" in text
    assert "User: hello" in text


class BrokenMemoryFabric:
    async def retrieve(self, query):
        raise RuntimeError("offline")

    async def record_turn(self, **kwargs):
        raise RuntimeError("offline")

    async def record_action_resume(self, **kwargs):
        raise RuntimeError("offline")


class SimpleProvider:
    provider_id = "provider.simple"

    async def supports(self, capability):
        return True

    async def invoke(self, request):
        return ModelResponse("Cognition remains available.", self.provider_id, "simple-v1")


def test_memory_provider_failure_does_not_block_cognition():
    gateway = AetherCognitiveGateway(SimpleProvider(), memory_fabric=BrokenMemoryFabric())
    expression = asyncio.run(gateway.respond(Perception("text", "hello", "cli")))
    assert expression.content == "Cognition remains available."
    assert "memory-retrieve:RuntimeError" in expression.metadata["memory_retrieval"]["errors"]
    assert "memory-write:RuntimeError" in expression.metadata["memory_retrieval"]["errors"]
