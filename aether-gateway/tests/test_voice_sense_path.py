from __future__ import annotations

import asyncio
from pathlib import Path

from aether.events import EventBus
from aether.senses import SenseEventPath
from aether_gateway.adapters.voice_bridge import VoiceBridgeAdapter
from aether_gateway.cognition import EchoCognitiveAdapter


def test_voice_transcript_reaches_replaceable_speech_sink(tmp_path: Path) -> None:
    spoken: list[str] = []

    async def speech_sink(text: str) -> None:
        spoken.append(text)

    async def scenario() -> tuple[list, list]:
        voice = VoiceBridgeAdapter(speech_sink)
        path = SenseEventPath(EventBus(tmp_path / "voice-events.jsonl"), EchoCognitiveAdapter())
        consumer = asyncio.create_task(path.run(voice, limit=1))
        await voice.ingest_transcript(
            "  Halo Aether  ",
            source="test-microphone",
            metadata={"language": "id"},
        )
        results = await consumer
        return results, path.event_bus.replay()

    results, events = asyncio.run(scenario())

    assert spoken == ["Aether received: Halo Aether"]
    assert len(results) == 1
    assert events[0].payload["metadata"] == {"language": "id"}
    assert events[-2].payload["modality"] == "speech"
    assert events[-1].event_type == "expression.delivered"


def test_voice_bridge_rejects_empty_transcript() -> None:
    async def scenario() -> None:
        voice = VoiceBridgeAdapter()
        await voice.ingest_transcript("   ")

    try:
        asyncio.run(scenario())
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("expected ValueError")
