from __future__ import annotations

from aether_gateway.browser_senses.worker import LiveKitWorkerConfig


def test_livekit_fallback_configuration_is_ordered_and_credential_free(monkeypatch):
    monkeypatch.setenv("AETHER_STT_FALLBACK_MODELS", "openai/whisper-1,assemblyai/universal")
    monkeypatch.setenv("AETHER_TTS_FALLBACK_MODELS", "openai/gpt-4o-mini-tts,cartesia/sonic-3")
    monkeypatch.setenv("AETHER_TTS_FALLBACK_VOICES", "marin,cartesia-voice-id")

    config = LiveKitWorkerConfig.from_env()

    assert config.stt_fallback() == [
        {"model": "openai/whisper-1"},
        {"model": "assemblyai/universal"},
    ]
    assert config.tts_fallback() == [
        {"model": "openai/gpt-4o-mini-tts", "voice": "marin"},
        {"model": "cartesia/sonic-3", "voice": "cartesia-voice-id"},
    ]
    assert "API_KEY" not in str(config.readiness()["fallback"])


def test_livekit_tts_fallback_models_and_voices_must_align(monkeypatch):
    monkeypatch.setenv("AETHER_TTS_FALLBACK_MODELS", "one,two")
    monkeypatch.setenv("AETHER_TTS_FALLBACK_VOICES", "only-one")
    config = LiveKitWorkerConfig.from_env()

    try:
        config.tts_fallback()
    except ValueError as error:
        assert "must align" in str(error)
    else:
        raise AssertionError("misaligned fallback configuration was accepted")
