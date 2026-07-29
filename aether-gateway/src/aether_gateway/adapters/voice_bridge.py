"""Vendor-neutral voice bridge boundary.

This module owns neither STT nor TTS. Provider implementations push completed
transcripts into ``ingest_transcript`` and receive speech text through the
configured sink.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Mapping

from aether.contracts.senses import Expression, Perception, SenseAdapter

SpeechSink = Callable[[str], Awaitable[None]]


class VoiceBridgeAdapter(SenseAdapter):
    def __init__(self, speech_sink: SpeechSink | None = None, *, adapter_id: str = "sense.voice") -> None:
        self._queue: asyncio.Queue[Perception] = asyncio.Queue()
        self._speech_sink = speech_sink
        self._adapter_id = adapter_id

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def ingest_transcript(
        self,
        text: str,
        *,
        source: str = "microphone",
        correlation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        normalized = text.strip()
        if not normalized:
            raise ValueError("transcript must not be empty")
        await self._queue.put(
            Perception(
                modality="audio.transcript",
                content=normalized,
                source=source,
                metadata=dict(metadata or {}),
                correlation_id=correlation_id,
            )
        )

    async def perceive(self) -> AsyncIterator[Perception]:
        while True:
            yield await self._queue.get()

    async def express(self, expression: Expression) -> None:
        if expression.modality not in {"speech", "audio.speech"}:
            raise ValueError(f"Voice bridge cannot express modality: {expression.modality}")
        if self._speech_sink is None:
            raise RuntimeError("No speech sink configured")
        await self._speech_sink(str(expression.content))
