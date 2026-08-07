from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from datetime import datetime, timezone
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
from aether_gateway.browser_senses.turns import TurnClaimConflict


def png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", 2, 3)
        + b"\x08\x02\x00\x00\x00bounded-pixels"
    )


class FakeCognition:
    adapter_id = "cognition.fake"

    def __init__(self) -> None:
        self.calls = 0

    async def respond(self, perception: Perception) -> Expression:
        self.calls += 1
        if perception.modality == "image.frame":
            assert perception.content["image_data_url"].startswith("data:image/png;base64,")
            return Expression("text", "A whiteboard is visible.", perception.source, {"provider_id": "fake", "model_id": "vision"})
        return Expression("text", f"Aether heard: {perception.content}", perception.source, {"provider_id": "fake", "model_id": "text"})


def test_browser_session_text_and_bounded_vision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    cognition = FakeCognition()
    service = BrowserSenseService(
        tmp_path / "senses",
        SenseEventPath(EventBus(tmp_path / "sense-path.jsonl"), cognition),
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

    text = asyncio.run(service.handle_text(
        token,
        "Hello",
        turn_id="turn-text-1",
        correlation_id="corr-text-1",
        generation=0,
    ))
    assert text["response"] == "Aether heard: Hello"
    assert text["turn"]["turn_id"] == "turn-text-1"
    assert text["turn_status"]["state"] == "completed"
    assert cognition.calls == 1

    duplicate = asyncio.run(service.handle_text(
        token,
        "Hello",
        turn_id="turn-text-1",
        correlation_id="corr-text-1",
        generation=0,
    ))
    assert duplicate["replayed"] is True
    assert duplicate["turn_status"]["state"] == "completed"
    assert "response" not in duplicate
    assert cognition.calls == 1
    assert service.turn_status(token, "turn-text-1")["response_hash"] == hashlib.sha256(
        b"Aether heard: Hello"
    ).hexdigest()
    try:
        asyncio.run(service.handle_text(
            token,
            "Different text",
            turn_id="turn-text-1",
            correlation_id="corr-text-1",
            generation=0,
        ))
    except TurnClaimConflict:
        pass
    else:
        raise AssertionError("a stable turn ID must not be rebound to different cognition")

    consent = service.grant_vision_consent(
        token,
        device_id="device.1",
        source="camera",
        mode="one-shot",
    )
    png = png_bytes()
    vision = asyncio.run(service.handle_vision(
        token,
        device_id="device.1",
        consent_id=consent["consent_id"],
        source="camera",
        sequence_number=1,
        captured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        data_base64=base64.b64encode(png).decode(),
        content_type="image/png",
        prompt="What is visible?",
        width=2,
        height=3,
        turn_id="turn-vision-1",
        correlation_id="corr-vision-1",
        generation=0,
    ))
    assert vision["response"] == "A whiteboard is visible."
    assert vision["frame"]["deletion_outcome"] == "deleted"
    assert not list(service.frames_root.glob("*.raw"))
    assert service.status()["store"]["vision_frames"] == 1
    assert service.status()["store"]["tracks"] == 1
    assert service.status()["turn_ledger"] == {
        "claims": 2,
        "events": 4,
        "interruptions": 0,
    }
    event_text = (tmp_path / "sense-path.jsonl").read_text(encoding="utf-8")
    assert "bounded-pixels" not in event_text
    assert "<redacted-media>" in event_text


class FailingVisionCognition:
    adapter_id = "cognition.failing-vision"

    async def respond(self, perception: Perception) -> Expression:
        if perception.modality == "image.frame":
            raise RuntimeError("vision provider failed")
        return Expression("text", "ok", perception.source)


def test_failed_vision_turn_still_deletes_raw_working_frame(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    service = BrowserSenseService(
        tmp_path / "senses",
        SenseEventPath(EventBus(tmp_path / "sense-path.jsonl"), FailingVisionCognition()),
        event_bus=EventBus(tmp_path / "browser-events.jsonl"),
        token_codec=BrowserSessionTokenCodec("x" * 48),
        livekit_issuer=LiveKitTokenIssuer(),
        maximum_frame_bytes=100,
    )
    issued = service.issue_session(
        principal="founder",
        display_name="Founder",
        capabilities=(BrowserSenseCapability.CAMERA,),
    )
    token = issued["browser_session_token"]
    consent = service.grant_vision_consent(
        token, device_id="device.1", source="camera", mode="one-shot",
    )

    try:
        asyncio.run(service.handle_vision(
            token,
            device_id="device.1",
            consent_id=consent["consent_id"],
            source="camera",
            sequence_number=1,
            captured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            data_base64=base64.b64encode(png_bytes()).decode(),
            content_type="image/png",
            prompt="What is visible?",
            width=2,
            height=3,
            turn_id="turn-vision-failed",
            correlation_id="corr-vision-failed",
        ))
    except RuntimeError as exc:
        assert "vision provider failed" in str(exc)
    else:
        raise AssertionError("failing vision cognition must fail the turn")

    assert not list(service.frames_root.glob("*.raw"))
    assert service.status()["store"]["vision_frames"] == 1
    assert service.status()["vision"]["raw_frames_present"] == 0
    event_text = (tmp_path / "browser-events.jsonl").read_text(encoding="utf-8")
    assert "bounded-pixels" not in event_text
    assert "vision-turn-terminal" in event_text


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


class BlockingCognition:
    adapter_id = "cognition.blocking"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def respond(self, perception: Perception) -> Expression:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("canceled cognition must not return a late response")


class CancellationIgnoringCognition:
    adapter_id = "cognition.cancel-ignoring"

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def respond(self, perception: Perception) -> Expression:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return Expression(
                "text",
                "late response that must never be played",
                perception.source,
                {"provider_id": "cancel-ignoring", "model_id": "late"},
            )
        raise AssertionError("unreachable")


def test_interruption_cancels_active_generation_and_records_hash_only_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    cognition = BlockingCognition()
    service = BrowserSenseService(
        tmp_path / "senses",
        SenseEventPath(EventBus(tmp_path / "sense-path.jsonl"), cognition),
        event_bus=EventBus(tmp_path / "browser-events.jsonl"),
        token_codec=BrowserSessionTokenCodec("x" * 48),
        livekit_issuer=LiveKitTokenIssuer(),
    )
    issued = service.issue_session(
        principal="founder",
        display_name="Founder",
        capabilities=(BrowserSenseCapability.TEXT,),
    )
    token = issued["browser_session_token"]

    async def exercise() -> None:
        task = asyncio.create_task(service.handle_text(
            token,
            "Please stop this turn",
            turn_id="turn-cancel-1",
            correlation_id="corr-cancel-1",
            generation=0,
        ))
        await cognition.started.wait()
        receipt = service.interrupt_turn(
            token,
            turn_id="turn-cancel-1",
            correlation_id="corr-cancel-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            delivered_audio_ms=0,
            provider_cancel_supported=True,
            provider_cancelled=True,
        )
        assert receipt["state"] == "interrupted"
        assert receipt["late_result_disposition"] == "canceled-upstream"
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("active cognition task was not canceled")

    asyncio.run(exercise())
    status = service.turn_status(token, "turn-cancel-1")
    assert status["state"] == "interrupted"
    assert status["generation"] == 1
    journal = (tmp_path / "browser-events.jsonl").read_text(encoding="utf-8")
    assert "Please stop this turn" not in journal


def test_provider_that_ignores_cancel_has_late_result_hash_receipted_and_discarded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    cognition = CancellationIgnoringCognition()
    service = BrowserSenseService(
        tmp_path / "senses",
        SenseEventPath(EventBus(tmp_path / "sense-path.jsonl"), cognition),
        event_bus=EventBus(tmp_path / "browser-events.jsonl"),
        token_codec=BrowserSessionTokenCodec("x" * 48),
        livekit_issuer=LiveKitTokenIssuer(),
    )
    issued = service.issue_session(
        principal="founder",
        display_name="Founder",
        capabilities=(BrowserSenseCapability.TEXT,),
    )
    token = issued["browser_session_token"]

    async def exercise() -> None:
        task = asyncio.create_task(service.handle_text(
            token,
            "Return too late",
            turn_id="turn-late-1",
            correlation_id="corr-late-1",
            generation=0,
        ))
        await cognition.started.wait()
        service.interrupt_turn(
            token,
            turn_id="turn-late-1",
            correlation_id="corr-late-1",
            previous_generation=0,
            next_generation=1,
            reason="explicit_stop",
            delivered_audio_ms=0,
        )
        try:
            await task
        except TurnClaimConflict:
            pass
        else:
            raise AssertionError("late cognition result crossed the generation boundary")

    asyncio.run(exercise())
    status = service.turn_status(token, "turn-late-1")
    assert status["state"] == "interrupted"
    assert status["late_result_disposition"] == "discarded"
    assert status["late_response_hash"] == hashlib.sha256(
        b"late response that must never be played"
    ).hexdigest()
    journal = (tmp_path / "browser-events.jsonl").read_text(encoding="utf-8")
    assert "late response that must never be played" not in journal
    assert "late-result-discarded" in journal
