from pathlib import Path

from aether.runtime.tts import AetherTtsAudition, AetherTtsConfig, SynthesizedAudio, TtsProviderError


def make_audition(tmp_path: Path, **kwargs) -> AetherTtsAudition:
    config = AetherTtsConfig(aether_home=tmp_path, **kwargs)
    return AetherTtsAudition(config)


def test_local_fallback_writes_audible_wav_and_receipt(tmp_path):
    audition = make_audition(tmp_path, allow_external=False)
    result = audition.audition("Halo Dee, ini bukti fallback suara Aether.")

    audio_path = Path(result["audio_path"])
    metadata_path = Path(result["metadata_path"])

    assert result["provider"] == "local-wav-fallback"
    assert result["fallback_used"] is True
    assert result["content_type"] == "audio/wav"
    assert audio_path.read_bytes().startswith(b"RIFF")
    assert "local-wav-fallback" in metadata_path.read_text(encoding="utf-8")
    assert "tts.audition.completed" in (tmp_path / "runtime" / "body" / "receipts.jsonl").read_text(
        encoding="utf-8"
    )


def test_google_attempt_falls_back_when_provider_fails(tmp_path):
    class BrokenGoogleProvider:
        name = "google-cloud-tts"
        external = True

        def status(self):
            return {"provider": self.name, "configured": True, "ready": True}

        def synthesize(self, text, language_code, voice_name, audio_encoding):
            raise TtsProviderError("simulated google failure")

    audition = AetherTtsAudition(
        AetherTtsConfig(aether_home=tmp_path, allow_external=True),
        providers=[BrokenGoogleProvider()],
    )
    result = audition.audition("Fallback should still produce local audio.")

    assert result["provider"] == "local-wav-fallback"
    assert result["fallback_used"] is True
    assert result["attempts"][0]["provider"] == "google-cloud-tts"
    assert result["attempts"][0]["status"] == "failed"
    assert Path(result["audio_path"]).read_bytes().startswith(b"RIFF")


def test_synthesize_can_return_provider_audio_without_writing(tmp_path):
    class ReadyProvider:
        name = "google-cloud-tts"
        external = True

        def status(self):
            return {"provider": self.name, "configured": True, "ready": True}

        def synthesize(self, text, language_code, voice_name, audio_encoding):
            return SynthesizedAudio(
                provider=self.name,
                audio_bytes=b"FAKEAUDIO",
                content_type="audio/mpeg",
                extension="mp3",
                language_code=language_code,
                voice_name=voice_name,
                fallback_used=False,
            )

    audition = AetherTtsAudition(
        AetherTtsConfig(aether_home=tmp_path, allow_external=True),
        providers=[ReadyProvider()],
    )
    audio = audition.synthesize("Google TTS audition.", allow_external=True)

    assert audio.provider == "google-cloud-tts"
    assert audio.fallback_used is False
    assert audio.audio_bytes == b"FAKEAUDIO"
    assert not (tmp_path / "runtime" / "body" / "receipts.jsonl").exists()
