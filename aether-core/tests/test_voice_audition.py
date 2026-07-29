from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from aether.voice.adapters import GoogleCloudTTSAdapter, HttpResponse, ProviderHttpError
from aether.voice.audition import AuditionRunner
from aether.voice.contracts import (
    AuditionCorpusEntry,
    VoiceArtifact,
    VoiceProviderManifest,
    VoiceSynthesisRequest,
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        value = self.value
        self.value += 0.025
        return value


class Transport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls = []

    def post(self, url, *, headers, body, content_type):
        self.calls.append((url, headers, body, content_type))
        return self.response


class FakeProvider:
    def __init__(self, provider_id: str, priority: int, outcome) -> None:
        self._manifest = VoiceProviderManifest(
            provider_id=provider_id,
            model_id="model-v1",
            voice_id="voice-a",
            language="id-ID",
            output_format="mp3",
            credential_ref=f"env://{provider_id}",
            priority=priority,
        )
        self.outcome = outcome

    @property
    def manifest(self):
        return self._manifest

    def synthesize(self, request, resolve_credential):
        resolve_credential(self.manifest.credential_ref)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return VoiceArtifact(self.outcome, "audio/mpeg", "mp3")


def manifest(provider_id="google-cloud-tts", priority=1):
    return VoiceProviderManifest(
        provider_id=provider_id,
        model_id="neural2",
        voice_id="id-ID-Standard-A",
        language="id-ID",
        output_format="mp3",
        credential_ref="env://GOOGLE_ACCESS_TOKEN",
        priority=priority,
    )


def test_google_generator_decodes_audio_and_never_serializes_secret():
    audio = b"deterministic-google-audio"
    transport = Transport(
        HttpResponse(
            200,
            json.dumps({"audioContent": base64.b64encode(audio).decode()}).encode(),
            {},
        )
    )
    adapter = GoogleCloudTTSAdapter(manifest(), transport)
    request = VoiceSynthesisRequest("Halo Dee", "id-ID", "turn-1")

    result = adapter.synthesize(request, lambda ref: "secret-access-token")

    assert result.audio == audio
    _, headers, body, _ = transport.calls[0]
    assert headers["Authorization"] == "Bearer secret-access-token"
    assert b"secret-access-token" not in body
    assert adapter.manifest.credential_ref == "env://GOOGLE_ACCESS_TOKEN"


def test_fallback_detects_quota_and_selects_openai_with_hash_receipt():
    exhausted = ProviderHttpError(
        "google-cloud-tts",
        HttpResponse(429, b'{"error":{"code":"RESOURCE_EXHAUSTED"}}', {}),
    )
    google = FakeProvider("google-cloud-tts", 1, exhausted)
    openai = FakeProvider("openai-exact-tts", 2, b"openai-audio")
    runner = AuditionRunner(
        [openai, google],
        resolve_credential=lambda ref: "test-only",
        clock=Clock(),
    )

    artifact, receipt = runner.synthesize(
        VoiceSynthesisRequest("Halo", "id-ID", "turn-2"),
        allowed_data_policy_tags={"hosted"},
    )

    assert artifact.audio == b"openai-audio"
    assert receipt.provider_id == "openai-exact-tts"
    assert receipt.fallback_from == ("google-cloud-tts",)
    assert receipt.error_classifications == ("google-cloud-tts:quota_exhausted",)
    assert len(receipt.audio_sha256) == 64
    assert len(receipt.receipt_id) == 64
    assert receipt.attempt_count == 2
    assert receipt.total_latency_ms == pytest.approx(25.0)


def test_authentication_failure_does_not_retry_same_provider_and_falls_back():
    error = ProviderHttpError("google-cloud-tts", HttpResponse(401, b"unauthorized", {}))
    runner = AuditionRunner(
        [
            FakeProvider("google-cloud-tts", 1, error),
            FakeProvider("openai-exact-tts", 2, b"must-not-run"),
        ],
        resolve_credential=lambda ref: "test-only",
        clock=Clock(),
    )

    artifact, receipt = runner.synthesize(
        VoiceSynthesisRequest("Halo", "id-ID", "turn-3"),
        allowed_data_policy_tags={"hosted"},
    )
    assert artifact.audio == b"must-not-run"
    assert receipt.fallback_from == ("google-cloud-tts",)
    assert receipt.error_classifications == ("google-cloud-tts:authentication",)


def test_generator_writes_audio_and_three_deterministic_comparison_sheets(tmp_path: Path):
    runner = AuditionRunner(
        [FakeProvider("google-cloud-tts", 1, b"same-audio")],
        resolve_credential=lambda ref: "test-only",
        clock=Clock(),
    )
    records = runner.generate(
        [AuditionCorpusEntry("natural-id", "natural", "id-ID", "Selamat pagi, Dee.")],
        tmp_path,
    )

    assert len(records) == 1
    assert (tmp_path / records[0].sample_path).read_bytes() == b"same-audio"
    assert (tmp_path / "voice-comparison.json").is_file()
    assert (tmp_path / "voice-comparison.csv").is_file()
    markdown = (tmp_path / "voice-comparison.md").read_text()
    assert "Founder-entered" in markdown
    assert records[0].audio_sha256 in markdown


def test_manifest_is_credential_free_and_stably_serializable():
    public = manifest().public_dict()
    assert public["credential_ref"] == "env://GOOGLE_ACCESS_TOKEN"
    assert "secret" not in json.dumps(public).lower()
    assert public["capabilities"] == ["voice.tts"]
