from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from aether.contracts import Expression, Perception
from aether.events import EventBus
from aether.senses import SenseEventPath


class OneShotSense:
    adapter_id = "sense.test"

    def __init__(self) -> None:
        self.spoken: list[Expression] = []

    async def perceive(self) -> AsyncIterator[Perception]:
        yield Perception(modality="text", content="hello", source="test-user")

    async def express(self, expression: Expression) -> None:
        self.spoken.append(expression)


class TestCognition:
    adapter_id = "cognition.test"

    async def respond(self, perception: Perception) -> Expression:
        return Expression(modality="speech", content=f"reply:{perception.content}")


class BrokenCognition:
    adapter_id = "cognition.broken"

    async def respond(self, perception: Perception) -> Expression:
        raise RuntimeError("boom")


def test_full_sense_event_path_is_durable_and_causally_linked(tmp_path: Path) -> None:
    bus = EventBus(tmp_path / "events.jsonl")
    sense = OneShotSense()
    path = SenseEventPath(bus, TestCognition())

    results = asyncio.run(path.run(sense, limit=1))

    assert len(results) == 1
    assert [item.content for item in sense.spoken] == ["reply:hello"]
    assert sense.spoken[0].correlation_id == results[0].correlation_id

    events = bus.replay()
    assert [event.event_type for event in events] == [
        "perception.received",
        "cognition.requested",
        "cognition.completed",
        "expression.requested",
        "expression.delivered",
    ]
    assert {event.correlation_id for event in events} == {results[0].correlation_id}
    for previous, current in zip(events, events[1:]):
        assert current.causation_id == previous.event_id


def test_failure_is_durable_and_reraised(tmp_path: Path) -> None:
    bus = EventBus(tmp_path / "events.jsonl")
    path = SenseEventPath(bus, BrokenCognition())

    try:
        asyncio.run(path.handle(OneShotSense(), Perception(modality="text", content="x", source="u")))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    events = bus.replay()
    assert events[-1].event_type == "sense.path.failed"
    assert events[-1].payload["error_type"] == "RuntimeError"
    assert events[-1].causation_id == events[-2].event_id


def test_handle_preserves_supplied_correlation_id(tmp_path: Path) -> None:
    bus = EventBus(tmp_path / "events.jsonl")
    sense = OneShotSense()
    path = SenseEventPath(bus, TestCognition())
    perception = Perception(
        modality="audio.transcript",
        content="ping",
        source="microphone",
        correlation_id="corr.external",
    )

    result = asyncio.run(path.handle(sense, perception))

    assert result.correlation_id == "corr.external"
    assert sense.spoken[0].correlation_id == "corr.external"


def test_run_rejects_non_positive_limit(tmp_path: Path) -> None:
    bus = EventBus(tmp_path / "events.jsonl")
    path = SenseEventPath(bus, TestCognition())

    try:
        asyncio.run(path.run(OneShotSense(), limit=0))
    except ValueError as exc:
        assert "at least 1" in str(exc)
    else:
        raise AssertionError("expected ValueError")
