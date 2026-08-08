"""Provider-neutral contracts for browser microphone, camera, speaker, and text senses."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

SENSES_V1_CONTRACT_VERSION = "aether.senses.interaction.v1"
SENSES_V1_BOUNDED_CAPTURE_INTERVAL_SECONDS = 15


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


class BrowserSenseClientSessionState(StrEnum):
    BOOTSTRAP_REQUIRED = "bootstrap-required"
    BOOTSTRAP_PENDING = "bootstrap-pending"
    READY = "ready"
    CONNECTING = "connecting"
    ACTIVE_REALTIME = "active-realtime"
    ACTIVE_DEGRADED = "active-degraded"
    RECONNECTING = "reconnecting"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class BrowserSenseTurnState(StrEnum):
    IDLE = "idle"
    WAKE_ARMED = "wake-armed"
    LISTENING = "listening"
    COMMITTING = "committing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTING = "interrupting"
    AWAITING_APPROVAL = "awaiting-approval"


class BrowserSenseOperatingMode(StrEnum):
    FULL_REALTIME = "full-realtime"
    VOICE_FALLBACK = "voice-fallback"
    TEXT_SPEECH = "text-speech"
    TEXT_ONLY = "text-only"
    STATUS_ONLY = "status-only"
    OFFLINE = "offline"


class BrowserSenseRuntimeProfile(StrEnum):
    GOVERNED_PIPELINE = "GOVERNED_PIPELINE"
    NATIVE_AUDIO_EXPERIMENTAL = "NATIVE_AUDIO_EXPERIMENTAL"


class BrowserSenseConsentSource(StrEnum):
    CAMERA = "camera"
    SCREEN = "screen"


class BrowserSenseConsentMode(StrEnum):
    PREVIEW_LOCAL = "preview-local"
    ONE_SHOT = "one-shot"
    BOUNDED = "bounded"


class BrowserSenseConsentState(StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class BrowserSenseInterruptionReason(StrEnum):
    USER_BARGE_IN = "user_barge_in"
    EXPLICIT_STOP = "explicit_stop"
    COMPETING_INPUT = "competing_input"
    DISCONNECT = "disconnect"
    SUSPEND = "suspend"


class BrowserSenseLateResultDisposition(StrEnum):
    NOT_APPLICABLE = "not-applicable"
    CANCELED_UPSTREAM = "canceled-upstream"
    DISCARDED = "discarded"


class BrowserSenseCapabilityActionState(StrEnum):
    NONE = "none"
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting-approval"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELING = "canceling"
    CANCELED = "canceled"
    RECONCILING = "reconciling"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


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
    runtime_profile: BrowserSenseRuntimeProfile | None = None
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
        if self.runtime_profile is not None and not isinstance(self.runtime_profile, BrowserSenseRuntimeProfile):
            object.__setattr__(self, "runtime_profile", BrowserSenseRuntimeProfile(self.runtime_profile))
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
class BrowserSenseConsentRecord:
    consent_id: str
    session_id: str
    source: BrowserSenseConsentSource
    mode: BrowserSenseConsentMode
    state: BrowserSenseConsentState
    granted_at: str
    recorded_at: str
    expires_at: str | None = None
    closed_at: str | None = None
    capture_interval_seconds: int | None = None
    sequence_number: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, BrowserSenseConsentSource):
            object.__setattr__(self, "source", BrowserSenseConsentSource(self.source))
        if not isinstance(self.mode, BrowserSenseConsentMode):
            object.__setattr__(self, "mode", BrowserSenseConsentMode(self.mode))
        if not isinstance(self.state, BrowserSenseConsentState):
            object.__setattr__(self, "state", BrowserSenseConsentState(self.state))
        _require_text(self.consent_id, "browser sense consent ID")
        _require_text(self.session_id, "browser sense consent session ID")
        _require_text(self.granted_at, "browser sense consent granted time")
        _require_text(self.recorded_at, "browser sense consent recorded time")
        if self.sequence_number < 0:
            raise ValueError("browser sense consent sequence number must not be negative")
        if self.state is BrowserSenseConsentState.GRANTED and self.closed_at is not None:
            raise ValueError("active browser sense consent must not have a closed time")
        if self.state in {BrowserSenseConsentState.REVOKED, BrowserSenseConsentState.EXPIRED}:
            _require_text(self.closed_at, "terminal browser sense consent closed time")
        if self.mode is BrowserSenseConsentMode.BOUNDED:
            if self.capture_interval_seconds != SENSES_V1_BOUNDED_CAPTURE_INTERVAL_SECONDS:
                raise ValueError("bounded browser sense consent requires the frozen 15-second capture interval")
            _require_text(self.expires_at, "bounded browser sense consent expiry")
        elif self.capture_interval_seconds is not None:
            raise ValueError("only bounded browser sense consent may define a capture interval")


@dataclass(frozen=True)
class BrowserSenseInterruptionReceipt:
    receipt_id: str
    session_id: str
    turn_id: str
    reason: BrowserSenseInterruptionReason
    requested_at: str
    audio_silent_at: str
    previous_generation: int
    next_generation: int
    delivered_audio_ms: int | None = None
    provider_cancel_supported: bool = False
    provider_cancelled: bool = False
    late_result_disposition: BrowserSenseLateResultDisposition = BrowserSenseLateResultDisposition.NOT_APPLICABLE
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, BrowserSenseInterruptionReason):
            object.__setattr__(self, "reason", BrowserSenseInterruptionReason(self.reason))
        if not isinstance(self.late_result_disposition, BrowserSenseLateResultDisposition):
            object.__setattr__(
                self,
                "late_result_disposition",
                BrowserSenseLateResultDisposition(self.late_result_disposition),
            )
        _require_text(self.receipt_id, "browser sense interruption receipt ID")
        _require_text(self.session_id, "browser sense interruption session ID")
        _require_text(self.turn_id, "browser sense interruption turn ID")
        _require_text(self.requested_at, "browser sense interruption request time")
        _require_text(self.audio_silent_at, "browser sense interruption audio-silent time")
        if self.previous_generation < 0 or self.next_generation != self.previous_generation + 1:
            raise ValueError("browser sense interruption must increment the turn generation exactly once")
        if self.delivered_audio_ms is not None and self.delivered_audio_ms < 0:
            raise ValueError("browser sense delivered audio duration must not be negative")
        if self.provider_cancelled and not self.provider_cancel_supported:
            raise ValueError("browser sense provider cancellation cannot succeed when unsupported")


@dataclass(frozen=True)
class BrowserSenseCapabilityActionReceipt:
    receipt_id: str
    action_id: str
    session_id: str
    correlation_id: str
    capability_name: str
    exact_action_hash: str
    state: BrowserSenseCapabilityActionState
    observed_at: str
    adapter_manifest_hash: str | None = None
    approval_request_id: str | None = None
    authoritative_receipt_id: str | None = None
    cancel_supported: bool = False
    control_request_id: str | None = None
    cancellation_status: str | None = None
    reconciliation_status: str | None = None
    progress: float | None = None
    safe_summary: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.state, BrowserSenseCapabilityActionState):
            object.__setattr__(self, "state", BrowserSenseCapabilityActionState(self.state))
        _require_text(self.receipt_id, "browser sense capability action receipt ID")
        _require_text(self.action_id, "browser sense capability action ID")
        _require_text(self.session_id, "browser sense capability action session ID")
        _require_text(self.correlation_id, "browser sense capability action correlation ID")
        _require_text(self.capability_name, "browser sense capability name")
        _require_text(self.observed_at, "browser sense capability action observed time")
        _require_sha256(self.exact_action_hash, "browser sense exact-action hash")
        if self.state is BrowserSenseCapabilityActionState.NONE:
            raise ValueError("browser sense capability action receipts must describe an action state")
        if (
            self.adapter_manifest_hash is not None
            or self.state is not BrowserSenseCapabilityActionState.UNAVAILABLE
        ):
            _require_sha256(self.adapter_manifest_hash, "browser sense adapter manifest hash")
        if self.state is BrowserSenseCapabilityActionState.AWAITING_APPROVAL:
            _require_text(self.approval_request_id, "browser sense approval request ID")
        terminal = {
            BrowserSenseCapabilityActionState.SUCCEEDED,
            BrowserSenseCapabilityActionState.FAILED,
            BrowserSenseCapabilityActionState.CANCELED,
            BrowserSenseCapabilityActionState.REJECTED,
            BrowserSenseCapabilityActionState.UNAVAILABLE,
        }
        if self.state in terminal:
            _require_text(self.authoritative_receipt_id, "terminal browser sense authoritative receipt ID")
        if self.cancellation_status is not None:
            if self.cancellation_status not in {
                "requested", "unsupported", "not-confirmed", "confirmed"
            }:
                raise ValueError("unknown browser sense cancellation status")
            _require_text(self.control_request_id, "browser sense cancellation control request ID")
        if self.reconciliation_status is not None:
            if self.reconciliation_status not in {"not-confirmed", "confirmed"}:
                raise ValueError("unknown browser sense reconciliation status")
            _require_text(self.control_request_id, "browser sense reconciliation control request ID")
        if self.state is BrowserSenseCapabilityActionState.CANCELING:
            if self.cancellation_status != "requested":
                raise ValueError("canceling action requires a requested cancellation receipt")
        if self.state is BrowserSenseCapabilityActionState.CANCELED:
            if self.cancellation_status != "confirmed":
                raise ValueError("canceled action requires a confirmed cancellation receipt")
        if self.state is BrowserSenseCapabilityActionState.RECONCILING:
            if self.reconciliation_status != "not-confirmed":
                raise ValueError("reconciling action must remain not-confirmed")
        if self.progress is not None and not 0.0 <= self.progress <= 1.0:
            raise ValueError("browser sense capability action progress must be between zero and one")


@dataclass(frozen=True)
class VisionFrameReceipt:
    frame_id: str
    session_id: str
    consent_id: str
    source: BrowserSenseConsentSource
    sequence_number: int
    content_hash: str
    byte_count: int
    content_type: str
    width: int
    height: int
    captured_at: str
    accepted_at: str
    ephemeral_handle: str
    prompt_hash: str
    deletion_outcome: str
    deleted_at: str
    deletion_reason: str
    turn_id: str
    correlation_id: str
    outcome: str
    provider_id: str | None = None
    model_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, BrowserSenseConsentSource):
            object.__setattr__(self, "source", BrowserSenseConsentSource(self.source))
        _require_text(self.frame_id, "vision frame ID")
        _require_text(self.session_id, "vision frame session ID")
        _require_text(self.consent_id, "vision frame consent ID")
        if self.sequence_number < 1:
            raise ValueError("vision frame sequence must be positive")
        if self.byte_count < 1:
            raise ValueError("vision frame must contain bytes")
        if self.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported vision frame content type")
        if self.width < 1 or self.height < 1:
            raise ValueError("vision frame dimensions must be positive")
        _require_sha256(self.content_hash, "vision frame content hash")
        _require_sha256(self.prompt_hash, "vision frame prompt hash")
        _require_text(self.captured_at, "vision frame capture time")
        _require_text(self.accepted_at, "vision frame accepted time")
        _require_text(self.deleted_at, "vision frame deletion time")
        _require_text(self.deletion_reason, "vision frame deletion reason")
        _require_text(self.turn_id, "vision frame turn ID")
        _require_text(self.correlation_id, "vision frame correlation ID")
        _require_text(self.outcome, "vision frame outcome")
        if self.deletion_outcome not in {"deleted", "swept"}:
            raise ValueError("vision frame receipt requires proven deletion")
        if (
            not self.ephemeral_handle.strip()
            or self.ephemeral_handle != self.frame_id
            or "/" in self.ephemeral_handle
            or "\\" in self.ephemeral_handle
        ):
            raise ValueError("vision frame ephemeral handle must not be a storage path")


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


_BROWSER_SENSE_ACTION_TRANSITIONS: Mapping[
    BrowserSenseCapabilityActionState, frozenset[BrowserSenseCapabilityActionState]
] = {
    BrowserSenseCapabilityActionState.NONE: frozenset({
        BrowserSenseCapabilityActionState.PROPOSED,
        BrowserSenseCapabilityActionState.UNAVAILABLE,
    }),
    BrowserSenseCapabilityActionState.PROPOSED: frozenset({
        BrowserSenseCapabilityActionState.AWAITING_APPROVAL,
        BrowserSenseCapabilityActionState.QUEUED,
        BrowserSenseCapabilityActionState.REJECTED,
        BrowserSenseCapabilityActionState.UNAVAILABLE,
    }),
    BrowserSenseCapabilityActionState.AWAITING_APPROVAL: frozenset({
        BrowserSenseCapabilityActionState.QUEUED,
        BrowserSenseCapabilityActionState.REJECTED,
    }),
    BrowserSenseCapabilityActionState.QUEUED: frozenset({BrowserSenseCapabilityActionState.RUNNING}),
    BrowserSenseCapabilityActionState.RUNNING: frozenset({
        BrowserSenseCapabilityActionState.SUCCEEDED,
        BrowserSenseCapabilityActionState.FAILED,
        BrowserSenseCapabilityActionState.CANCELING,
        BrowserSenseCapabilityActionState.RECONCILING,
    }),
    BrowserSenseCapabilityActionState.CANCELING: frozenset({BrowserSenseCapabilityActionState.CANCELED}),
    BrowserSenseCapabilityActionState.RECONCILING: frozenset({
        BrowserSenseCapabilityActionState.SUCCEEDED,
        BrowserSenseCapabilityActionState.FAILED,
    }),
}


def require_browser_sense_v1_runtime_profile(
    profile: BrowserSenseRuntimeProfile | str | None,
) -> BrowserSenseRuntimeProfile:
    try:
        normalized = BrowserSenseRuntimeProfile(profile) if profile is not None else None
    except ValueError as exc:
        raise ValueError("unknown browser sense runtime profile") from exc
    if normalized is not BrowserSenseRuntimeProfile.GOVERNED_PIPELINE:
        raise ValueError("Aether Senses v1 requires the GOVERNED_PIPELINE runtime profile")
    return normalized


def require_browser_sense_action_transition(
    current: BrowserSenseCapabilityActionState | str,
    target: BrowserSenseCapabilityActionState | str,
) -> BrowserSenseCapabilityActionState:
    current_state = BrowserSenseCapabilityActionState(current)
    target_state = BrowserSenseCapabilityActionState(target)
    if current_state is target_state:
        return target_state
    if target_state not in _BROWSER_SENSE_ACTION_TRANSITIONS.get(current_state, frozenset()):
        raise ValueError(
            "invalid browser sense capability action transition: "
            f"{current_state.value} -> {target_state.value}"
        )
    return target_state


def _require_text(value: str | None, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _require_sha256(value: str | None, label: str) -> str:
    normalized = _require_text(value, label)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


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
    if data.get("runtime_profile") is None:
        data.pop("runtime_profile", None)
    return _normalized(data)


def browser_sense_session_hash(session: BrowserSenseSession) -> str:
    payload = browser_sense_session_payload(session)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
