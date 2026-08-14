from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

import livekit.rtc as rtc
from livekit.agents import tts
from livekit.agents import APIConnectOptions

from aether.voice.adapters import GeminiExactTextTTSAdapter
from aether.voice.contracts import VoiceArtifact, VoiceSynthesisRequest
from aether.voice.runtime import VoiceDeploymentManifest


class _GeminiChunkedStream(tts.ChunkedStream):
    """ChunkedStream implementation for Gemini Exact-Text TTS."""

    def __init__(
        self,
        *,
        tts: "GeminiExactTTS",
        input_text: str,
        conn_options: APIConnectOptions,
        delivery_instruction: str,
    ) -> None:
        super().__init__(
            tts=tts,
            input_text=input_text,
            conn_options=conn_options,
        )
        self._delivery_instruction = delivery_instruction
        self._manifest = tts._manifest
        self._adapter = tts._adapter

    async def _main_task(self) -> None:
        try:
            # Build synthesis request
            request = VoiceSynthesisRequest(
                exact_text=self._input_text,
                delivery_instruction=self._delivery_instruction,
            )

            # Resolve credential from env
            def resolve_credential(ref: str) -> str:
                if ref.startswith("env://"):
                    name = ref[len("env://"):]
                    value = os.environ.get(name)
                    if not value:
                        raise RuntimeError(f"credential reference is not configured: {ref}")
                    return value
                raise ValueError(f"unsupported credential reference: {ref}")

            # Synthesize via Gemini adapter
            artifact: VoiceArtifact = await self._adapter.synthesize(
                request, resolve_credential
            )

            # Artifact contains PCM audio bytes
            audio_bytes = artifact.bytes
            if not audio_bytes:
                raise RuntimeError("Gemini TTS returned empty audio")

            # Create AudioFrame from PCM (L16, 24kHz, mono)
            # artifact is L16 PCM @ 24000 Hz, 1 channel
            frame = rtc.AudioFrame(
                data=audio_bytes,
                sample_rate=self._manifest.sample_rate,
                num_channels=self._manifest.channels,
                samples_per_channel=len(audio_bytes) // 2,  # 16-bit = 2 bytes/sample
            )

            # Push synthesized audio frame
            segment_id = str(uuid.uuid4())
            await self._event_ch.send(
                tts.SynthesizedAudio(
                    frame=frame,
                    request_id=str(uuid.uuid4()),
                    is_final=True,
                    segment_id=segment_id,
                    delta_text=self._input_text,
                )
            )

        except Exception as e:
            self._event_ch.close()
            raise


class GeminiExactTTS(tts.TTS):
    """LiveKit TTS wrapper for Gemini Exact-Text TTS (Founder Alpha).

    Wraps `GeminiExactTextTTSAdapter` to provide a LiveKit-compatible TTS
    with 24 kHz PCM output, voice `Aoede`, model `gemini-3.1-flash-tts-preview`.
    """

    def __init__(
        self,
        manifest_path: str = "configs/runtime/gemini_tts_founder_alpha.yaml",
        transport: Optional[Any] = None,
    ) -> None:
        # Load manifest
        self._manifest = VoiceDeploymentManifest.from_yaml(manifest_path)
        self._adapter = GeminiExactTextTTSAdapter(self._manifest)

        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=self._manifest.sample_rate,
            num_channels=self._manifest.channels,
        )

    @property
    def model(self) -> str:
        return self._manifest.model_id

    @property
    def provider(self) -> str:
        return self._manifest.provider_id

    def synthesize(
        self,
        text: str,
        *,
        conn_options: Optional[APIConnectOptions] = None,
        delivery_instruction: str = "Speak naturally and clearly.",
    ) -> tts.ChunkedStream:
        return _GeminiChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options or APIConnectOptions(),
            delivery_instruction=delivery_instruction,
        )

    def stream(
        self,
        *,
        conn_options: Optional[APIConnectOptions] = None,
    ) -> tts.SynthesizeStream:
        # Non-streaming TTS: return a stream that buffers full text then synthesizes
        return _GeminiSynthesizeStream(self)


class _GeminiSynthesizeStream(tts.SynthesizeStream):
    """Streaming adapter for non-streaming Gemini TTS (buffers all text then synthesizes)."""

    def __init__(self, tts: GeminiExactTTS, conn_options: Optional[APIConnectOptions] = None) -> None:
        super().__init__(tts=tts, conn_options=conn_options or APIConnectOptions())
        self._buffer: List[str] = []

    def push_text(self, text: str) -> None:
        if text:
            self._buffer.append(text)

    def flush(self) -> None:
        if self._buffer:
            text = "".join(self._buffer)
            self._buffer.clear()
            if text.strip():
                chunked = self._tts.synthesize(text)
                asyncio.create_task(self._consume_chunked(chunked))

    async def _consume_chunked(self, chunked: tts.ChunkedStream) -> None:
        async for audio in chunked:
            self._event_ch.send(audio)
        self._event_ch.close()

    def end_input(self) -> None:
        self.flush()
        if not self._buffer:
            self._event_ch.close()

    def close(self) -> None:
        self._event_ch.close()


# Register in LiveKit plugin registry for inference.TTS.from_model_string()
# Not strictly needed since we use the class directly, but good for completeness.
try:
    from livekit.agents import inference
    inference._TTS_MODEL_REGISTRY["gemini-exact-tts"] = lambda model, **kwargs: GeminiExactTTS()
except Exception:
    pass