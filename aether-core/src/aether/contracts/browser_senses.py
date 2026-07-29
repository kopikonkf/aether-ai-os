"""Provider-neutral contracts for browser microphone, camera, speaker, and text senses."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence


class BrowserSenseCapability(StrEnum):
    TEXT = "text"
    MICROPHONE = "microphone"
    SPEAKER = "speaker"
    CAMERA = "camera"
    SCREEN_SHARE = "screen-share"


class BrowserSenseTransport(StrEnum):
    LIVEKIT = "livekit"
    HTTP_KEYFRAME = "http-keyframe"
    WEBSOCKET_TEXT = "websocket-text"


class BrowserSenseSessionState(StrEnum):
    ISSUED = "issued"
    CONNECTING = "connecting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    CLOSED = "closed"
    EXPIRED = "expired"


class MediaTrackKind(StrEnum):
    AUDIO = "audio"
    VIDEO = "video"
    DATA = "data"


@dataclass(frozen=True)
class BrowserSenseSession:
    session_id: str
    room_name: str
    participant_identity: str
    capabilities: Sequence[BrowserSenseCapability]
    transports: Sequence[BrowserSenseTransport]
    state: BrowserSenseSessionState
    issued_at: str
    expires_at: str
    token_hash: str
    principal: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.session_id.strip() or not self.room_name.strip() or not self.participant_identity.strip():
            raise ValueError("browser sense session identifiers must not be empty")
        if not self.capabilities:
            raise ValueError("browser sense session requires at least one capability")
        if not self.transports:
            raise ValueError("browser sense session requires at least one transport")
        if not self.token_hash.strip():
            raise ValueError("browser sense token hash must not be empty")
        expected = browser_sense_session_hash(self)
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("browser sense session fingerprint mismatch")
        object.__setattr__(self, "fingerprint", expected)


@dataclass(frozen=True)
class BrowserMediaTrackReceipt:
    receipt_id: str
    session_id: str
    track_sid: str
    kind: MediaTrackKind
    source: str
    muted: bool
    observed_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisionFrameReceipt:
    frame_id: str
    session_id: str
    content_hash: str
    byte_count: int
    content_type: str
    width: int | None
    height: int | None
    observed_at: str
    storage_reference: str
    prompt: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.byte_count < 1:
            raise ValueError("vision frame must contain bytes")
        if self.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported vision frame content type")
        if not self.content_hash.strip() or not self.storage_reference.strip():
            raise ValueError("vision frame requires content hash and storage reference")


@dataclass(frozen=True)
class BrowserSenseTurnReceipt:
    turn_id: str
    session_id: str
    input_modality: str
    output_modality: str
    transcript_hash: str | None
    vision_frame_id: str | None
    correlation_id: str
    started_at: str
    completed_at: str
    provider_id: str | None = None
    model_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _normalized(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _normalized(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    if isinstance(value, (tuple, list)):
        return [_normalized(item) for item in value]
    return value


def browser_sense_session_payload(session: BrowserSenseSession) -> dict[str, Any]:
    data = asdict(session)
    data.pop("fingerprint", None)
    return _normalized(data)


def browser_sense_session_hash(session: BrowserSenseSession) -> str:
    payload = browser_sense_session_payload(session)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
