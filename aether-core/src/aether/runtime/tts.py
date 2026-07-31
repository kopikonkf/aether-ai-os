"""Google TTS audition with deterministic local fallback proof."""
from __future__ import annotations

import base64
import io
import json
import math
import os
import struct
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib import error, parse, request

from aether.runtime.paths import AetherHome, get_aether_home


DEFAULT_LANGUAGE_CODE = "id-ID"
DEFAULT_VOICE_NAME = "id-ID-Standard-A"
DEFAULT_AUDIO_ENCODING = "MP3"
DEFAULT_GOOGLE_TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_CHARS = 900


def _bool_env(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _module_available(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _text_fingerprint(text: str) -> dict[str, Any]:
    import hashlib

    clean = text.strip()
    return {
        "text_sha256": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        "text_chars": len(clean),
        "text_preview": clean[:80],
    }


class TtsProviderError(RuntimeError):
    """Base error for TTS provider attempts."""


class TtsProviderUnavailable(TtsProviderError):
    """Provider is not configured or cannot run in this environment."""


@dataclass(frozen=True)
class AetherTtsConfig:
    aether_home: Path
    language_code: str = DEFAULT_LANGUAGE_CODE
    voice_name: str = DEFAULT_VOICE_NAME
    audio_encoding: str = DEFAULT_AUDIO_ENCODING
    allow_external: bool = False
    google_enabled: bool = True
    gtts_enabled: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_chars: int = DEFAULT_MAX_CHARS
    google_tts_url: str = DEFAULT_GOOGLE_TTS_URL

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        aether_home: Path | str | None = None,
    ) -> "AetherTtsConfig":
        env = os.environ if environ is None else environ
        return cls(
            aether_home=Path(aether_home or env.get("AETHER_HOME") or get_aether_home()),
            language_code=env.get("AETHER_TTS_LANGUAGE_CODE", DEFAULT_LANGUAGE_CODE),
            voice_name=env.get("AETHER_TTS_VOICE_NAME", DEFAULT_VOICE_NAME),
            audio_encoding=env.get("AETHER_TTS_AUDIO_ENCODING", DEFAULT_AUDIO_ENCODING).upper(),
            allow_external=_bool_env(env.get("AETHER_TTS_ALLOW_EXTERNAL"), default=False),
            google_enabled=_bool_env(env.get("AETHER_TTS_GOOGLE_ENABLED"), default=True),
            gtts_enabled=_bool_env(env.get("AETHER_TTS_GTTS_FALLBACK_ENABLED"), default=False),
            timeout_seconds=float(env.get("AETHER_TTS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
            max_chars=int(env.get("AETHER_TTS_MAX_CHARS", DEFAULT_MAX_CHARS)),
            google_tts_url=env.get("AETHER_TTS_GOOGLE_URL", DEFAULT_GOOGLE_TTS_URL),
        )


@dataclass
class SynthesizedAudio:
    provider: str
    audio_bytes: bytes
    content_type: str
    extension: str
    language_code: str
    voice_name: str
    fallback_used: bool
    attempts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class TtsProvider(Protocol):
    name: str
    external: bool

    def status(self) -> dict[str, Any]: ...

    def synthesize(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
    ) -> SynthesizedAudio: ...


class GoogleCloudTtsProvider:
    name = "google-cloud-tts"
    external = True

    def __init__(
        self,
        config: AetherTtsConfig,
        environ: Mapping[str, str] | None = None,
    ):
        self.config = config
        self.env = os.environ if environ is None else environ

    def status(self) -> dict[str, Any]:
        api_key = bool(self.env.get("GOOGLE_TTS_API_KEY") or self.env.get("GOOGLE_API_KEY"))
        access_token = bool(self.env.get("GOOGLE_OAUTH_ACCESS_TOKEN"))
        service_account = bool(self.env.get("GOOGLE_APPLICATION_CREDENTIALS"))
        client_library = _module_available("google.cloud.texttospeech")
        configured = self.config.google_enabled and (
            api_key or access_token or (service_account and client_library)
        )
        if not self.config.google_enabled:
            reason = "disabled"
        elif api_key:
            reason = "rest_api_key"
        elif access_token:
            reason = "rest_bearer_token"
        elif service_account and client_library:
            reason = "google_cloud_client"
        elif service_account:
            reason = "client_library_missing"
        elif client_library:
            reason = "credentials_missing"
        else:
            reason = "dependency_and_credentials_missing"
        return {
            "provider": self.name,
            "external": True,
            "enabled": self.config.google_enabled,
            "configured": configured,
            "ready": configured and self.config.allow_external,
            "external_allowed": self.config.allow_external,
            "credential_present": api_key or access_token or service_account,
            "client_library_available": client_library,
            "reason": reason,
            "language_code": self.config.language_code,
            "voice_name": self.config.voice_name,
            "audio_encoding": self.config.audio_encoding,
        }

    def synthesize(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
    ) -> SynthesizedAudio:
        status = self.status()
        if not status["configured"]:
            raise TtsProviderUnavailable(status["reason"])
        api_key = self.env.get("GOOGLE_TTS_API_KEY") or self.env.get("GOOGLE_API_KEY")
        access_token = self.env.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        if api_key or access_token:
            return self._synthesize_rest(text, language_code, voice_name, audio_encoding, api_key, access_token)
        return self._synthesize_client(text, language_code, voice_name, audio_encoding)

    def _synthesize_rest(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
        api_key: str | None,
        access_token: str | None,
    ) -> SynthesizedAudio:
        url = self.config.google_tts_url
        if api_key:
            url = f"{url}?{parse.urlencode({'key': api_key})}"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice_name},
            "audioConfig": {"audioEncoding": audio_encoding},
        }
        headers = {"content-type": "application/json"}
        if access_token:
            headers["authorization"] = f"Bearer {access_token}"
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, error.URLError, json.JSONDecodeError) as exc:
            raise TtsProviderError(str(exc)) from exc
        audio_content = raw.get("audioContent")
        if not audio_content:
            raise TtsProviderError("google_tts_missing_audio_content")
        audio_bytes = base64.b64decode(audio_content)
        extension = "mp3" if audio_encoding == "MP3" else "wav"
        content_type = "audio/mpeg" if extension == "mp3" else "audio/wav"
        return SynthesizedAudio(
            provider=self.name,
            audio_bytes=audio_bytes,
            content_type=content_type,
            extension=extension,
            language_code=language_code,
            voice_name=voice_name,
            fallback_used=False,
            metadata={"transport": "rest"},
        )

    def _synthesize_client(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
    ) -> SynthesizedAudio:
        try:
            from google.cloud import texttospeech
        except Exception as exc:
            raise TtsProviderUnavailable("google_cloud_client_missing") from exc
        try:
            client = texttospeech.TextToSpeechClient()
            synthesis_input = texttospeech.SynthesisInput(text=text)
            voice = texttospeech.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name,
            )
            encoding = getattr(texttospeech.AudioEncoding, audio_encoding)
            audio_config = texttospeech.AudioConfig(audio_encoding=encoding)
            response = client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config,
            )
        except Exception as exc:
            raise TtsProviderError(str(exc)) from exc
        extension = "mp3" if audio_encoding == "MP3" else "wav"
        content_type = "audio/mpeg" if extension == "mp3" else "audio/wav"
        return SynthesizedAudio(
            provider=self.name,
            audio_bytes=bytes(response.audio_content),
            content_type=content_type,
            extension=extension,
            language_code=language_code,
            voice_name=voice_name,
            fallback_used=False,
            metadata={"transport": "google_cloud_client"},
        )


class GTtsFallbackProvider:
    name = "gtts-fallback"
    external = True

    def __init__(self, config: AetherTtsConfig):
        self.config = config

    def status(self) -> dict[str, Any]:
        available = _module_available("gtts")
        configured = self.config.gtts_enabled and available
        return {
            "provider": self.name,
            "external": True,
            "enabled": self.config.gtts_enabled,
            "configured": configured,
            "ready": configured and self.config.allow_external,
            "dependency_available": available,
            "reason": "ready" if configured else "disabled_or_dependency_missing",
        }

    def synthesize(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
    ) -> SynthesizedAudio:
        status = self.status()
        if not status["configured"]:
            raise TtsProviderUnavailable(status["reason"])
        try:
            from gtts import gTTS
        except Exception as exc:
            raise TtsProviderUnavailable("gtts_missing") from exc
        tmp = io.BytesIO()
        try:
            tts = gTTS(text=text, lang=language_code.split("-")[0], slow=False)
            tts.write_to_fp(tmp)
        except Exception as exc:
            raise TtsProviderError(str(exc)) from exc
        return SynthesizedAudio(
            provider=self.name,
            audio_bytes=tmp.getvalue(),
            content_type="audio/mpeg",
            extension="mp3",
            language_code=language_code,
            voice_name=voice_name,
            fallback_used=True,
            metadata={"transport": "gtts"},
        )


class LocalWavFallbackProvider:
    name = "local-wav-fallback"
    external = False

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "external": False,
            "configured": True,
            "ready": True,
            "reason": "built_in_proof_audio",
        }

    def synthesize(
        self,
        text: str,
        language_code: str,
        voice_name: str,
        audio_encoding: str,
    ) -> SynthesizedAudio:
        return SynthesizedAudio(
            provider=self.name,
            audio_bytes=self._tone(text),
            content_type="audio/wav",
            extension="wav",
            language_code=language_code,
            voice_name="aether-local-proof-tone",
            fallback_used=True,
            metadata={"transport": "stdlib_wave", "proof": "audible_tone_not_speech"},
        )

    def _tone(self, text: str) -> bytes:
        sample_rate = 16000
        duration = min(max(0.75 + len(text.strip()) * 0.006, 0.75), 2.4)
        frequency = 440 + (sum(text.encode("utf-8")) % 220)
        amplitude = 9500
        frames = int(sample_rate * duration)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for index in range(frames):
                cycle_position = (index % sample_rate) / sample_rate
                envelope = 1.0 if cycle_position < 0.82 else 0.0
                value = int(amplitude * envelope * math.sin(2 * math.pi * frequency * index / sample_rate))
                wav.writeframesraw(struct.pack("<h", value))
        return buffer.getvalue()


class AetherTtsAudition:
    """Audition Google TTS, then prove fallback if Google is unavailable."""

    def __init__(
        self,
        config: AetherTtsConfig,
        providers: list[TtsProvider] | None = None,
        fallback_provider: TtsProvider | None = None,
    ):
        self.config = config
        self.home = AetherHome(config.aether_home)
        self.home.ensure()
        self.providers = providers if providers is not None else self._default_providers()
        self.fallback_provider = fallback_provider or LocalWavFallbackProvider()

    def _default_providers(self) -> list[TtsProvider]:
        providers: list[TtsProvider] = [GoogleCloudTtsProvider(self.config)]
        if self.config.gtts_enabled:
            providers.append(GTtsFallbackProvider(self.config))
        return providers

    def status(self) -> dict[str, Any]:
        return {
            "surface": "aether-tts-audition",
            "language_code": self.config.language_code,
            "voice_name": self.config.voice_name,
            "allow_external": self.config.allow_external,
            "auditions_dir": str(self.home.tts_auditions),
            "providers": [provider.status() for provider in self.providers],
            "fallback": self.fallback_provider.status(),
        }

    def synthesize(
        self,
        text: str,
        *,
        allow_external: bool | None = None,
        language_code: str | None = None,
        voice_name: str | None = None,
        audio_encoding: str | None = None,
    ) -> SynthesizedAudio:
        clean = self._validate_text(text)
        external_allowed = self.config.allow_external if allow_external is None else allow_external
        language = language_code or self.config.language_code
        voice = voice_name or self.config.voice_name
        encoding = (audio_encoding or self.config.audio_encoding).upper()
        attempts: list[dict[str, Any]] = []

        for provider in self.providers:
            status = provider.status()
            if provider.external and not external_allowed:
                attempts.append({"provider": provider.name, "status": "skipped", "reason": "external_disabled"})
                continue
            if not status.get("configured", False):
                attempts.append({"provider": provider.name, "status": "unavailable", "reason": status.get("reason")})
                continue
            try:
                audio = provider.synthesize(clean, language, voice, encoding)
            except TtsProviderError as exc:
                attempts.append({"provider": provider.name, "status": "failed", "reason": str(exc)})
                continue
            audio.attempts = attempts + [{"provider": provider.name, "status": "ok"}]
            return audio

        fallback = self.fallback_provider.synthesize(clean, language, voice, "LINEAR16")
        fallback.attempts = attempts + [{"provider": self.fallback_provider.name, "status": "ok"}]
        return fallback

    def audition(
        self,
        text: str,
        *,
        allow_external: bool | None = None,
        language_code: str | None = None,
        voice_name: str | None = None,
        audio_encoding: str | None = None,
    ) -> dict[str, Any]:
        clean = self._validate_text(text)
        audio = self.synthesize(
            clean,
            allow_external=allow_external,
            language_code=language_code,
            voice_name=voice_name,
            audio_encoding=audio_encoding,
        )
        audition_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        audio_path = self.home.tts_auditions / f"{audition_id}.{audio.extension}"
        metadata_path = self.home.tts_auditions / f"{audition_id}.json"
        audio_path.write_bytes(audio.audio_bytes)
        metadata = {
            "audition_id": audition_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": audio.provider,
            "fallback_used": audio.fallback_used,
            "content_type": audio.content_type,
            "audio_path": str(audio_path),
            "language_code": audio.language_code,
            "voice_name": audio.voice_name,
            "attempts": audio.attempts,
            "metadata": audio.metadata,
            **_text_fingerprint(clean),
        }
        metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
        receipt = self._record_receipt("tts.audition.completed", metadata | {"metadata_path": str(metadata_path)})
        return {
            "accepted": True,
            "status": "completed",
            "audition_id": audition_id,
            "provider": audio.provider,
            "fallback_used": audio.fallback_used,
            "content_type": audio.content_type,
            "extension": audio.extension,
            "audio_path": str(audio_path),
            "metadata_path": str(metadata_path),
            "receipt_id": receipt["receipt_id"],
            "attempts": audio.attempts,
        }

    def _validate_text(self, text: str) -> str:
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("text must not be empty")
        if len(clean) > self.config.max_chars:
            raise ValueError(f"text must be {self.config.max_chars} characters or fewer")
        return clean

    def _record_receipt(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        receipt = {
            "receipt_id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "body": "aether-runtime-body",
            "payload": payload,
        }
        line = json.dumps(receipt, sort_keys=True)
        self.home.receipts.parent.mkdir(parents=True, exist_ok=True)
        with self.home.receipts.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.home.latest_receipt.write_text(line + "\n", encoding="utf-8")
        return receipt
