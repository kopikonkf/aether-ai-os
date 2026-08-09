"""Thin vendor adapters. HTTP and credential access are injected and replaceable."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Mapping, Protocol

from .contracts import (
    CredentialResolver,
    VoiceArtifact,
    VoiceProviderManifest,
    VoiceSynthesisRequest,
    VoiceTranscriptionReceipt,
    VoiceTranscriptionRequest,
    canonical_hash,
    sha256_bytes,
)


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]

    def json(self) -> Mapping[str, object]:
        value = json.loads(self.body)
        if not isinstance(value, dict):
            raise ValueError("provider response must be a JSON object")
        return value


class HttpTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
    ) -> HttpResponse: ...


class RequestsTransport:
    """Optional live transport; imported lazily to keep deterministic CI offline."""

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes,
        content_type: str,
    ) -> HttpResponse:
        import requests

        response = requests.post(
            url,
            headers={**headers, "Content-Type": content_type},
            data=body,
            timeout=self.timeout_seconds,
        )
        return HttpResponse(response.status_code, response.content, dict(response.headers))


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.casefold() == name.casefold():
            return value
    return None


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw = _header_value(headers, "Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _provider_error_fields(response: HttpResponse) -> tuple[str, str]:
    try:
        payload = response.json()
    except Exception:
        return "", response.body[:512].decode("utf-8", errors="replace")
    error = payload.get("error", payload)
    if isinstance(error, Mapping):
        code = error.get("code") or error.get("type") or error.get("status") or ""
        message = error.get("message") or error.get("detail") or ""
        return str(code), str(message)
    if error:
        return "", str(error)
    return "", ""


class ProviderHttpError(RuntimeError):
    def __init__(self, provider_id: str, response: HttpResponse) -> None:
        self.provider_id = provider_id
        self.status_code = response.status_code
        self.response_body = response.body[:4096]
        self.error_code, self.error_message = _provider_error_fields(response)
        self.retry_after_seconds = _retry_after_seconds(response.headers)
        detail = f": {self.error_code}" if self.error_code else ""
        if self.error_message:
            detail = f"{detail}: {self.error_message}" if detail else f": {self.error_message}"
        super().__init__(f"{provider_id} returned HTTP {response.status_code}{detail}")


class _JsonTTSAdapter:
    def __init__(self, manifest: VoiceProviderManifest, transport: HttpTransport) -> None:
        self._manifest = manifest
        self._transport = transport

    @property
    def manifest(self) -> VoiceProviderManifest:
        return self._manifest

    def _post_json(
        self, url: str, payload: Mapping[str, object], headers: Mapping[str, str]
    ) -> HttpResponse:
        response = self._transport.post(
            url,
            headers=headers,
            body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            content_type="application/json",
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderHttpError(self.manifest.provider_id, response)
        return response


class GoogleCloudTTSAdapter(_JsonTTSAdapter):
    endpoint = "https://texttospeech.googleapis.com/v1/text:synthesize"

    def synthesize(
        self, request: VoiceSynthesisRequest, resolve_credential: CredentialResolver
    ) -> VoiceArtifact:
        token = resolve_credential(self.manifest.credential_ref)
        payload = {
            "input": {"text": request.text},
            "voice": {
                "languageCode": self.manifest.language,
                "name": self.manifest.voice_id,
            },
            "audioConfig": {
                "audioEncoding": self.manifest.output_format.upper(),
                "speakingRate": request.speaking_rate,
                "pitch": request.pitch,
            },
        }
        response = self._post_json(
            self.endpoint, payload, {"Authorization": f"Bearer {token}"}
        )
        audio = response.json().get("audioContent")
        if not isinstance(audio, str):
            raise ValueError("Google TTS response did not contain audioContent")
        return VoiceArtifact(base64.b64decode(audio, validate=True), "audio/mpeg", "mp3")


class GeminiExactTextTTSAdapter(_JsonTTSAdapter):
    """Gemini TTS peripheral that receives one bounded exact-text prompt."""

    endpoint = "https://generativelanguage.googleapis.com/v1beta/interactions"

    def synthesize(
        self, request: VoiceSynthesisRequest, resolve_credential: CredentialResolver
    ) -> VoiceArtifact:
        if not request.delivery_instruction:
            raise ValueError("Gemini exact-text TTS requires a compiled delivery instruction")
        token = resolve_credential(self.manifest.credential_ref)
        response = self._post_json(
            self.endpoint,
            {
                "model": self.manifest.model_id,
                "input": request.exact_text_provider_input,
                "response_format": {"type": "audio"},
                "generation_config": {
                    "speech_config": [{"voice": self.manifest.voice_id}]
                },
            },
            {"x-goog-api-key": token},
        )
        payload = response.json()
        audio = self._extract_audio(payload)

        if audio is None:
            raise TypeError("Gemini TTS response did not contain audio output")
        content_type = audio.get("mime_type") or audio.get("mimeType") or "audio/pcm;rate=24000"
        if content_type.startswith("audio/wav"):
            extension = "wav"
        elif content_type.startswith("audio/mpeg"):
            extension = "mp3"
        else:
            extension = "pcm"
        return VoiceArtifact(audio["bytes"], content_type, extension)

    @staticmethod
    def _extract_audio(payload: Mapping[str, object]) -> dict[str, object] | None:
        """Locate the synthesized audio part in the v1beta interactions response.

        The interactions endpoint returns audio as a ``steps[].content[]`` part
        shaped ``{mime_type, data, channels, sample_rate}``. The legacy
        ``output_audio`` / ``outputAudio`` single-part shape is also accepted so
        older fixtures and deployments keep working.
        """
        legacy = payload.get("output_audio") or payload.get("outputAudio")
        if isinstance(legacy, Mapping):
            data = legacy.get("data")
            if isinstance(data, str):
                decoded = _b64decode(data)
                if decoded:
                    return {"bytes": decoded, "mime_type": legacy.get("mime_type") or legacy.get("mimeType")}
        steps = payload.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                content = step.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    if str(part.get("type", "")) != "audio":
                        continue
                    data = part.get("data")
                    if not isinstance(data, str):
                        continue
                    decoded = _b64decode(data)
                    if decoded:
                        return {
                            "bytes": decoded,
                            "mime_type": part.get("mime_type") or part.get("mime_type_string") or "audio/pcm;rate=24000",
                        }
        return None


def _b64decode(value: str) -> bytes | None:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None
    return decoded or None


class OpenAIExactTextTTSAdapter(_JsonTTSAdapter):
    endpoint = "https://api.openai.com/v1/audio/speech"

    def synthesize(
        self, request: VoiceSynthesisRequest, resolve_credential: CredentialResolver
    ) -> VoiceArtifact:
        token = resolve_credential(self.manifest.credential_ref)
        response = self._post_json(
            self.endpoint,
            {
                "model": self.manifest.model_id,
                "voice": self.manifest.voice_id,
                "input": request.text,
                "response_format": self.manifest.output_format,
            },
            {"Authorization": f"Bearer {token}"},
        )
        return VoiceArtifact(response.body, "audio/mpeg", self.manifest.output_format)


class CartesiaTTSAdapter(_JsonTTSAdapter):
    endpoint = "https://api.cartesia.ai/tts/bytes"

    def synthesize(
        self, request: VoiceSynthesisRequest, resolve_credential: CredentialResolver
    ) -> VoiceArtifact:
        token = resolve_credential(self.manifest.credential_ref)
        response = self._post_json(
            self.endpoint,
            {
                "model_id": self.manifest.model_id,
                "transcript": request.text,
                "voice": {"mode": "id", "id": self.manifest.voice_id},
                "language": request.language,
                "output_format": {
                    "container": self.manifest.output_format,
                    "encoding": "mp3",
                    "sample_rate": 44100,
                },
            },
            {
                "X-API-Key": token,
                "Cartesia-Version": "2025-04-16",
            },
        )
        return VoiceArtifact(response.body, "audio/mpeg", self.manifest.output_format)


class OpenAITranscriptionAdapter:
    endpoint = "https://api.openai.com/v1/audio/transcriptions"

    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        credential_ref: str,
        transport: HttpTransport,
        clock,
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.credential_ref = credential_ref
        self.transport = transport
        self.clock = clock

    def transcribe(
        self, request: VoiceTranscriptionRequest, resolve_credential: CredentialResolver
    ) -> tuple[str, VoiceTranscriptionReceipt]:
        started = self.clock()
        boundary = "aether-voice-boundary"
        fields = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{self.model_id}\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{request.language}\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.bin\"\r\n"
            f"Content-Type: {request.content_type}\r\n\r\n",
        ]
        body = "".join(fields).encode("utf-8") + request.audio + f"\r\n--{boundary}--\r\n".encode()
        response = self.transport.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {resolve_credential(self.credential_ref)}"},
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderHttpError(self.provider_id, response)
        text = response.json().get("text")
        if not isinstance(text, str):
            raise ValueError("OpenAI transcription response did not contain text")
        total = (self.clock() - started) * 1000
        payload = {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "correlation_id": request.correlation_id,
            "audio_sha256": request.audio_sha256,
            "transcript_sha256": sha256_bytes(text.encode("utf-8")),
            "total_latency_ms": total,
        }
        return text, VoiceTranscriptionReceipt(**payload, receipt_id=canonical_hash(payload))
