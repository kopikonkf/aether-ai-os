from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from aether.contracts import (
    BrowserSenseCapability,
    BrowserSenseRuntimeProfile,
    Expression,
    MediaTrackKind,
    Perception,
)
from aether.events import EventBus
from aether.senses import SenseEventPath
from aether_gateway.browser_senses import BrowserSenseService, BrowserSessionTokenCodec, LiveKitTokenIssuer


class FakeCognition:
    adapter_id = "cognition.fake"

    async def respond(self, perception: Perception) -> Expression:
        if perception.modality == "image.frame":
            assert perception.content["image_data_url"].startswith("data:image/jpeg;base64,")
            return Expression("text", "A whiteboard is visible.", perception.source, {"provider_id": "fake", "model_id": "vision"})
        return Expression("text", f"Aether heard: {perception.content}", perception.source, {"provider_id": "fake", "model_id": "text"})


def test_browser_session_text_and_bounded_vision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    service = BrowserSenseService(
        tmp_path / "senses",
        SenseEventPath(EventBus(tmp_path / "sense-path.jsonl"), FakeCognition()),
        event_bus=EventBus(tmp_path / "browser-events.jsonl"),
        token_codec=BrowserSessionTokenCodec("x" * 48),
        livekit_issuer=LiveKitTokenIssuer(),
        maximum_frame_bytes=100,
    )
    issued = service.issue_session(
        principal="founder",
        display_name="Founder",
        capabilities=(BrowserSenseCapability.TEXT, BrowserSenseCapability.CAMERA),
    )
    token = issued["browser_session_token"]
    assert issued["livekit"]["ready"] is False
    assert "token_hash" not in issued["session"]
    assert issued["session"]["runtime_profile"] == "GOVERNED_PIPELINE"
    assert service.status()["contract_version"] == "aether.senses.interaction.v1"

    try:
        service.issue_session(
            principal="founder",
            display_name="Founder",
            capabilities=(BrowserSenseCapability.TEXT,),
            runtime_profile=BrowserSenseRuntimeProfile.NATIVE_AUDIO_EXPERIMENTAL,
        )
    except ValueError as exc:
        assert "GOVERNED_PIPELINE" in str(exc)
    else:
        raise AssertionError("native audio must not enter the v1 session path")

    track = service.record_track(token, track_sid="mic-1", kind=MediaTrackKind.AUDIO, source="microphone", muted=False)
    assert track.kind is MediaTrackKind.AUDIO

    text = asyncio.run(service.handle_text(token, "Hello"))
    assert text["response"] == "Aether heard: Hello"

    vision = asyncio.run(service.handle_vision(
        token,
        data_base64=base64.b64encode(b"jpeg-bytes").decode(),
        content_type="image/jpeg",
        prompt="What is visible?",
        width=10,
        height=10,
    ))
    assert vision["response"] == "A whiteboard is visible."
    assert service.status()["store"]["vision_frames"] == 1
    assert service.status()["store"]["tracks"] == 1
    event_text = (tmp_path / "sense-path.jsonl").read_text(encoding="utf-8")
    assert "jpeg-bytes" not in event_text
    assert "<redacted-media>" in event_text


def test_browser_session_token_detects_tampering() -> None:
    codec = BrowserSessionTokenCodec("s" * 48)
    token = codec.issue(session_id="s1", principal="founder", expires_at="2099-01-01T00:00:00Z")
    assert codec.verify(token)["session_id"] == "s1"
    try:
        codec.verify(token[:-1] + ("a" if token[-1] != "a" else "b"))
    except PermissionError:
        pass
    else:
        raise AssertionError("tampered token must be rejected")
