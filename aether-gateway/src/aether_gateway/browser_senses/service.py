"""Secure browser-sense session service.

LiveKit transports media. Aether remains the identity, cognition, memory, and
approval authority. Browser session tokens are short-lived and distinct from
the operator token and LiveKit participant token.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.browser_senses import BrowserSenseStore
from aether.contracts import (
    SENSES_V1_CONTRACT_VERSION,
    BrowserSenseCapability,
    BrowserSenseConsentSource,
    BrowserSenseInterruptionReason,
    BrowserSenseInterruptionReceipt,
    BrowserSenseLateResultDisposition,
    BrowserSenseRuntimeProfile,
    BrowserSenseSession,
    BrowserSenseSessionState,
    BrowserSenseTransport,
    BrowserSenseTurnReceipt,
    BrowserMediaTrackReceipt,
    MediaTrackKind,
    EventType,
    Perception,
    VisionFrameReceipt,
    require_browser_sense_v1_runtime_profile,
)
from aether.events import EventBus
from aether.senses import SenseEventPath
from aether.utils.ids import new_id
from aether.utils.time import utc_now
from aether_gateway.adapters import DirectTextSenseAdapter

from .turns import BrowserSenseTurnLedger, TurnClaim, TurnClaimConflict
from .vision import (
    BOUNDED_CAPTURE_INTERVAL_SECONDS,
    BOUNDED_CONSENT_LEASE_SECONDS,
    ORPHAN_FRAME_MAX_AGE_SECONDS,
    VisionConsentError,
    VisionDeletionError,
    VisionFrameValidationError,
    VisionLifecycle,
    validate_image,
)


class BrowserSenseAuthError(PermissionError):
    pass


class BrowserSessionTokenCodec:
    """Minimal HMAC token used only between Aether browser UI and Gateway."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("browser sense secret must be at least 32 bytes")
        self._secret = secret.encode("utf-8")

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue(self, *, session_id: str, principal: str, expires_at: str) -> str:
        payload = {
            "sid": session_id,
            "sub": principal,
            "exp": expires_at,
            "nonce": secrets.token_urlsafe(12),
        }
        encoded = self._b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = self._b64(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def verify(self, token: str) -> Mapping[str, str]:
        try:
            encoded, signature = token.split(".", 1)
        except ValueError as exc:
            raise BrowserSenseAuthError("invalid browser sense token") from exc
        expected = self._b64(hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise BrowserSenseAuthError("invalid browser sense token signature")
        try:
            payload = json.loads(self._unb64(encoded))
            expires_at = datetime.fromisoformat(str(payload["exp"]).replace("Z", "+00:00"))
        except Exception as exc:
            raise BrowserSenseAuthError("invalid browser sense token payload") from exc
        if expires_at <= datetime.now(timezone.utc):
            raise BrowserSenseAuthError("browser sense token expired")
        return {"session_id": str(payload["sid"]), "principal": str(payload["sub"]), "expires_at": str(payload["exp"])}


class LiveKitTokenIssuer:
    """Optional LiveKit participant token issuer using the official server SDK."""

    def __init__(self) -> None:
        self.url = str(os.environ.get("LIVEKIT_URL") or "").strip()
        self.api_key = str(os.environ.get("LIVEKIT_API_KEY") or "").strip()
        self.api_secret = str(os.environ.get("LIVEKIT_API_SECRET") or "").strip()
        self.agent_name = str(os.environ.get("LIVEKIT_AGENT_NAME") or "aether-sense").strip()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key and self.api_secret)

    def status(self) -> dict[str, Any]:
        try:
            from livekit import api as _api  # noqa: F401
            sdk_ready = True
        except ModuleNotFoundError:
            sdk_ready = False
        return {
            "configured": self.configured,
            "sdk_ready": sdk_ready,
            "url_configured": bool(self.url),
            "api_key_configured": bool(self.api_key),
            "api_secret_configured": bool(self.api_secret),
            "agent_name": self.agent_name,
            "ready": bool(self.configured and sdk_ready),
        }

    def issue(self, *, room_name: str, identity: str, name: str, ttl_seconds: int) -> dict[str, str]:
        if not self.configured:
            raise RuntimeError("LiveKit is not configured")
        try:
            from livekit import api
        except ModuleNotFoundError as exc:
            raise RuntimeError("livekit-api is not installed") from exc
        token = api.AccessToken(self.api_key, self.api_secret)
        token = token.with_identity(identity).with_name(name)
        token = token.with_ttl(timedelta(seconds=ttl_seconds))
        token = token.with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
            can_publish_data=True,
        ))
        # Room configuration support differs slightly across SDK releases. The
        # explicit agent dispatch endpoint remains available when the SDK does
        # not accept room config in the token builder.
        try:
            room_config = api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=self.agent_name)])
            token = token.with_room_config(room_config)
        except (AttributeError, TypeError):
            # Older server SDKs can still connect the participant. Deployments
            # using such versions must dispatch the named agent explicitly.
            pass
        return {
            "server_url": self.url,
            "participant_token": token.to_jwt(),
            "agent_name": self.agent_name,
        }


class BrowserSenseService:
    _IDENTITY_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

    def __init__(
        self,
        root: Path,
        sense_path: SenseEventPath,
        *,
        event_bus: EventBus,
        token_codec: BrowserSessionTokenCodec,
        livekit_issuer: LiveKitTokenIssuer | None = None,
        maximum_frame_bytes: int = 750_000,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self.root = root
        self.frames_root = root / "frames"
        self.frames_root.mkdir(parents=True, exist_ok=True)
        self.store = BrowserSenseStore(root / "browser-senses.sqlite3")
        self.turn_ledger = BrowserSenseTurnLedger(root / "browser-sense-turns.sqlite3")
        self._active_turns: dict[tuple[str, str], tuple[int, asyncio.Task[Any]]] = {}
        self.sense_path = sense_path
        self.event_bus = event_bus
        self.token_codec = token_codec
        self.livekit_issuer = livekit_issuer or LiveKitTokenIssuer()
        self.maximum_frame_bytes = maximum_frame_bytes
        self.default_ttl_seconds = default_ttl_seconds
        self.vision = VisionLifecycle(
            root / "vision-lifecycle.sqlite3",
            self.frames_root,
            maximum_frame_bytes=maximum_frame_bytes,
        )
        self.startup_orphan_frames_swept = self.vision.sweep_orphans(
            maximum_age_seconds=ORPHAN_FRAME_MAX_AGE_SECONDS - 5,
        )
        if self.startup_orphan_frames_swept:
            self.event_bus.emit(
                EventType.BROWSER_SENSE_VISION_FRAME_SWEPT,
                actor="aether.browser-senses",
                payload={
                    "swept_count": self.startup_orphan_frames_swept,
                    "maximum_age_seconds": ORPHAN_FRAME_MAX_AGE_SECONDS,
                },
                severity="warning",
            )

    @classmethod
    def _safe_identity(cls, value: str, fallback: str) -> str:
        cleaned = cls._IDENTITY_RE.sub("-", value.strip())[:80].strip("-._")
        return cleaned or fallback

    def issue_session(
        self,
        *,
        principal: str,
        display_name: str,
        capabilities: Sequence[BrowserSenseCapability],
        ttl_seconds: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        runtime_profile: BrowserSenseRuntimeProfile | str = BrowserSenseRuntimeProfile.GOVERNED_PIPELINE,
    ) -> dict[str, Any]:
        profile = require_browser_sense_v1_runtime_profile(runtime_profile)
        ttl = max(300, min(int(ttl_seconds or self.default_ttl_seconds), 86_400))
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=ttl)
        session_id = new_id("sense-session")
        room_name = self._safe_identity(f"aether-{session_id}", session_id)
        participant_identity = self._safe_identity(f"founder-{principal}-{secrets.token_hex(4)}", "founder")
        expires_at = expires.isoformat().replace("+00:00", "Z")
        browser_token = self.token_codec.issue(session_id=session_id, principal=principal, expires_at=expires_at)
        transports = [BrowserSenseTransport.HTTP_KEYFRAME, BrowserSenseTransport.WEBSOCKET_TEXT]
        livekit: dict[str, Any]
        try:
            livekit = {"ready": True, **self.livekit_issuer.issue(
                room_name=room_name,
                identity=participant_identity,
                name=display_name.strip() or principal,
                ttl_seconds=ttl,
            )}
            transports.insert(0, BrowserSenseTransport.LIVEKIT)
        except Exception as exc:
            livekit = {"ready": False, "error": f"{type(exc).__name__}: {exc}", **self.livekit_issuer.status()}
        session = BrowserSenseSession(
            session_id=session_id,
            room_name=room_name,
            participant_identity=participant_identity,
            capabilities=tuple(dict.fromkeys(capabilities)),
            transports=tuple(transports),
            state=BrowserSenseSessionState.ISSUED,
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=expires_at,
            token_hash=hashlib.sha256(browser_token.encode("utf-8")).hexdigest(),
            principal=principal,
            runtime_profile=profile,
            metadata={
                **dict(metadata or {}),
                "contract_version": SENSES_V1_CONTRACT_VERSION,
                "livekit_ready": bool(livekit.get("ready")),
            },
        )
        self.store.record_session(session)
        self.event_bus.emit(EventType.BROWSER_SENSE_SESSION_ISSUED, actor="aether.browser-senses", payload={
            "session_id": session.session_id,
            "room_name": session.room_name,
            "capabilities": [item.value for item in session.capabilities],
            "transports": [item.value for item in session.transports],
            "expires_at": session.expires_at,
            "runtime_profile": profile.value,
            "livekit_ready": bool(livekit.get("ready")),
            "fingerprint": session.fingerprint,
        })
        return {
            "session": self._session_dict(session),
            "browser_session_token": browser_token,
            "livekit": livekit,
        }

    def authenticate(self, token: str) -> BrowserSenseSession:
        payload = self.token_codec.verify(token)
        session = self.store.get_session(payload["session_id"])
        if not hmac.compare_digest(session.token_hash, hashlib.sha256(token.encode("utf-8")).hexdigest()):
            raise BrowserSenseAuthError("browser sense token does not match session")
        if session.state in {BrowserSenseSessionState.CLOSED, BrowserSenseSessionState.EXPIRED}:
            raise BrowserSenseAuthError(f"browser sense session is {session.state.value}")
        return session

    def mark_active(self, token: str, *, metadata: Mapping[str, Any] | None = None) -> BrowserSenseSession:
        session = self.authenticate(token)
        active = self.store.transition_session(session.session_id, BrowserSenseSessionState.ACTIVE, recorded_at=utc_now(), metadata=dict(metadata or {}))
        self.event_bus.emit(EventType.BROWSER_SENSE_SESSION_ACTIVE, actor="aether.browser-senses", payload={"session_id": active.session_id})
        return active

    def close(self, token: str, *, reason: str = "client-disconnected") -> BrowserSenseSession:
        session = self.authenticate(token)
        return self.close_session(session.session_id, reason=reason)

    def close_session(self, session_id: str, *, reason: str = "server-revoked") -> BrowserSenseSession:
        session = self.store.get_session(session_id)
        if session.state in {BrowserSenseSessionState.CLOSED, BrowserSenseSessionState.EXPIRED}:
            return session
        closed = self.store.transition_session(
            session.session_id,
            BrowserSenseSessionState.CLOSED,
            recorded_at=utc_now(),
            metadata={"close_reason": reason},
        )
        self.event_bus.emit(EventType.BROWSER_SENSE_SESSION_CLOSED, actor="aether.browser-senses", payload={"session_id": closed.session_id, "reason": reason})
        for consent in self.vision.revoke_session(session.session_id, reason=reason):
            self.event_bus.emit(
                EventType.BROWSER_SENSE_VISION_CONSENT_REVOKED,
                actor="aether.browser-senses",
                payload=consent,
            )
        return closed

    def grant_vision_consent(
        self,
        token: str,
        *,
        device_id: str,
        source: str,
        mode: str,
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        consent = self.vision.grant_consent(
            session_id=session.session_id,
            device_id=device_id,
            source=source,
            mode=mode,
            capabilities=(item.value for item in session.capabilities),
        )
        self.event_bus.emit(
            EventType.BROWSER_SENSE_VISION_CONSENT_GRANTED,
            actor="aether.browser-senses",
            payload=consent,
        )
        return consent

    def revoke_vision_consent(
        self,
        token: str,
        *,
        device_id: str,
        consent_id: str,
        reason: str,
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        consent = self.vision.revoke_consent(
            session_id=session.session_id,
            device_id=device_id,
            consent_id=consent_id,
            reason=reason,
        )
        self.event_bus.emit(
            EventType.BROWSER_SENSE_VISION_CONSENT_REVOKED,
            actor="aether.browser-senses",
            payload=consent,
        )
        return consent

    def sweep_orphan_frames(self) -> int:
        swept = self.vision.sweep_orphans(
            maximum_age_seconds=ORPHAN_FRAME_MAX_AGE_SECONDS - 5,
        )
        if swept:
            self.event_bus.emit(
                EventType.BROWSER_SENSE_VISION_FRAME_SWEPT,
                actor="aether.browser-senses",
                payload={
                    "swept_count": swept,
                    "maximum_age_seconds": ORPHAN_FRAME_MAX_AGE_SECONDS,
                },
                severity="warning",
            )
        return swept

    def record_track(
        self,
        token: str,
        *,
        track_sid: str,
        kind: MediaTrackKind,
        source: str,
        muted: bool,
        metadata: Mapping[str, Any] | None = None,
    ) -> BrowserMediaTrackReceipt:
        session = self.authenticate(token)
        receipt = BrowserMediaTrackReceipt(
            receipt_id=new_id("sense-track"),
            session_id=session.session_id,
            track_sid=self._safe_identity(track_sid, new_id("track")),
            kind=kind,
            source=source.strip() or "browser",
            muted=muted,
            observed_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        self.store.record_track(receipt)
        self.event_bus.emit(EventType.BROWSER_SENSE_TRACK_OBSERVED, actor="aether.browser-senses", payload={
            "receipt_id": receipt.receipt_id,
            "session_id": session.session_id,
            "track_sid": receipt.track_sid,
            "kind": receipt.kind.value,
            "source": receipt.source,
            "muted": receipt.muted,
        })
        return receipt

    @staticmethod
    def _turn_request_hash(modality: str, content_hash: str) -> str:
        payload = json.dumps(
            {"modality": modality, "content_hash": content_hash},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _claim_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
        request_hash: str,
        retry_of_turn_id: str | None,
    ) -> TurnClaim:
        claim = self.turn_ledger.claim(
            session_id=session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            request_hash=request_hash,
            retry_of_turn_id=retry_of_turn_id,
        )
        if claim.first_claim:
            self.event_bus.emit(
                EventType.BROWSER_SENSE_TURN_ACCEPTED,
                actor="aether.browser-senses",
                payload={
                    "receipt_id": claim.status["receipt_id"],
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "correlation_id": correlation_id,
                    "generation": generation,
                    "retry_of_turn_id": retry_of_turn_id,
                    "request_hash": request_hash,
                },
                correlation_id=correlation_id,
            )
        return claim

    async def _execute_claimed_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        generation: int,
        adapter: DirectTextSenseAdapter,
        perception: Perception,
        input_modality: str,
        output_modality: str | None,
        transcript_hash: str | None,
        vision_frame_id: str | None,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
        extra_response: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("browser sense turn requires an asyncio task")
        key = (session_id, turn_id)
        self._active_turns[key] = (generation, task)
        started = utc_now()
        try:
            trace = await self.sense_path.handle(adapter, perception)
            expression = adapter.expressions[-1]
            terminal_receipt_id = new_id("sense-turn-receipt")
            response_hash = hashlib.sha256(expression.content.encode("utf-8")).hexdigest()
            turn = BrowserSenseTurnReceipt(
                turn_id=turn_id,
                session_id=session_id,
                input_modality=input_modality,
                output_modality=output_modality or expression.modality,
                transcript_hash=transcript_hash,
                vision_frame_id=vision_frame_id,
                correlation_id=correlation_id,
                started_at=started,
                completed_at=utc_now(),
                provider_id=expression.metadata.get("provider_id"),
                model_id=expression.metadata.get("model_id"),
                metadata={
                    **dict(metadata or {}),
                    "generation": generation,
                    "terminal_receipt_id": terminal_receipt_id,
                    "response_hash": response_hash,
                },
            )
            try:
                turn_status = self.turn_ledger.complete(
                    session_id=session_id,
                    turn_id=turn_id,
                    correlation_id=correlation_id,
                    generation=generation,
                    response_hash=response_hash,
                    terminal_receipt_id=terminal_receipt_id,
                )
            except TurnClaimConflict:
                latest = self.turn_ledger.status(session_id=session_id, turn_id=turn_id)
                if latest["state"] != "interrupted":
                    raise
                discarded = self.turn_ledger.discard_late_result(
                    session_id=session_id,
                    turn_id=turn_id,
                    correlation_id=correlation_id,
                    original_generation=generation,
                    response_hash=response_hash,
                )
                self.event_bus.emit(
                    EventType.BROWSER_SENSE_LATE_RESULT_DISCARDED,
                    actor=actor,
                    payload=discarded,
                    correlation_id=correlation_id,
                )
                raise
            self.store.record_turn(turn)
            self.event_bus.emit(
                EventType.BROWSER_SENSE_TURN_COMPLETED,
                actor=actor,
                payload={
                    "turn_id": turn.turn_id,
                    "session_id": session_id,
                    "input_modality": input_modality,
                    "output_modality": turn.output_modality,
                    "correlation_id": correlation_id,
                    "generation": generation,
                    "terminal_receipt_id": terminal_receipt_id,
                    "response_hash": response_hash,
                },
                correlation_id=correlation_id,
            )
            return {
                **dict(extra_response or {}),
                "response": expression.content,
                "expression": asdict(expression),
                "trace": asdict(trace),
                "turn": asdict(turn),
                "turn_status": turn_status,
                "replayed": False,
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                status = self.turn_ledger.fail(
                    session_id=session_id,
                    turn_id=turn_id,
                    correlation_id=correlation_id,
                    generation=generation,
                    failure_code=type(exc).__name__,
                )
                self.event_bus.emit(
                    EventType.BROWSER_SENSE_TURN_FAILED,
                    actor=actor,
                    payload=status,
                    severity="error",
                    correlation_id=correlation_id,
                )
            except TurnClaimConflict:
                # A concurrent interruption is already the authoritative terminal state.
                pass
            raise
        finally:
            if self._active_turns.get(key) == (generation, task):
                self._active_turns.pop(key, None)

    async def handle_text(
        self,
        token: str,
        text: str,
        *,
        turn_id: str,
        correlation_id: str,
        generation: int = 0,
        retry_of_turn_id: str | None = None,
        modality: str = "browser.text",
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        transcript_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        claim = self._claim_turn(
            session_id=session.session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            request_hash=self._turn_request_hash(modality, transcript_hash),
            retry_of_turn_id=retry_of_turn_id,
        )
        if not claim.first_claim:
            return {"replayed": True, "turn_status": claim.status}
        adapter = DirectTextSenseAdapter(adapter_id="sense.browser")
        return await self._execute_claimed_turn(
            session_id=session.session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            adapter=adapter,
            perception=Perception(
                modality=modality,
                content=normalized,
                source=f"browser:{session.session_id}",
                metadata={
                    "channel": "browser",
                    "session_id": f"browser:{session.session_id}",
                    "response_modality": "text",
                    "browser_sense_session_id": session.session_id,
                    "turn_id": turn_id,
                    "turn_generation": generation,
                },
                correlation_id=correlation_id,
            ),
            input_modality=modality,
            output_modality=None,
            transcript_hash=transcript_hash,
            vision_frame_id=None,
            actor="aether.browser-senses",
            metadata={"retry_of_turn_id": retry_of_turn_id},
        )

    async def handle_worker_transcript(
        self,
        *,
        room_name: str,
        participant_identity: str,
        text: str,
        turn_id: str,
        correlation_id: str,
        generation: int = 0,
        retry_of_turn_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            session = self.store.get_session_by_room(room_name)
            browser_session_id = session.session_id
        except KeyError:
            browser_session_id = self._safe_identity(room_name, "livekit-room")
        normalized = text.strip()
        if not normalized:
            raise ValueError("transcript must not be empty")
        transcript_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        claim = self._claim_turn(
            session_id=browser_session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            request_hash=self._turn_request_hash("audio.transcript", transcript_hash),
            retry_of_turn_id=retry_of_turn_id,
        )
        if not claim.first_claim:
            return {"replayed": True, "turn_status": claim.status}
        adapter = DirectTextSenseAdapter(adapter_id="sense.livekit-worker")
        return await self._execute_claimed_turn(
            session_id=browser_session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            adapter=adapter,
            perception=Perception(
                modality="audio.transcript",
                content=normalized,
                source=f"livekit:{room_name}:{participant_identity}",
                metadata={
                    "channel": "livekit",
                    "session_id": f"browser:{browser_session_id}",
                    "response_modality": "text",
                    "browser_sense_session_id": browser_session_id,
                    "livekit_room": room_name,
                    "participant_identity": participant_identity,
                    "turn_id": turn_id,
                    "turn_generation": generation,
                },
                correlation_id=correlation_id,
            ),
            input_modality="audio.transcript",
            output_modality="audio.speech",
            transcript_hash=transcript_hash,
            vision_frame_id=None,
            actor="aether.livekit-worker",
            metadata={
                "transport": BrowserSenseTransport.LIVEKIT.value,
                "participant_identity": participant_identity,
                "retry_of_turn_id": retry_of_turn_id,
            },
        )

    async def handle_vision(
        self,
        token: str,
        *,
        device_id: str,
        consent_id: str,
        source: str,
        sequence_number: int,
        captured_at: str,
        data_base64: str,
        content_type: str,
        prompt: str,
        width: int,
        height: int,
        turn_id: str,
        correlation_id: str,
        generation: int = 0,
        retry_of_turn_id: str | None = None,
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        required_capability = {
            "camera": BrowserSenseCapability.CAMERA,
            "screen": BrowserSenseCapability.SCREEN_SHARE,
        }.get(source)
        if required_capability is None:
            raise VisionConsentError("vision source must be camera or screen")
        if required_capability not in session.capabilities:
            raise BrowserSenseAuthError(
                f"{required_capability.value} capability was not granted"
            )
        maximum_encoded_bytes = ((self.maximum_frame_bytes + 2) // 3) * 4
        if len(data_base64) > maximum_encoded_bytes:
            raise ValueError(
                f"encoded vision frame exceeds the {self.maximum_frame_bytes}-byte policy"
            )
        try:
            raw = base64.b64decode(data_base64, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 vision frame") from exc
        actual_width, actual_height = validate_image(
            raw,
            content_type=content_type,
            maximum_frame_bytes=self.maximum_frame_bytes,
            declared_width=width,
            declared_height=height,
        )
        digest = hashlib.sha256(raw).hexdigest()
        normalized_prompt = prompt.strip() or "Describe only what is materially visible in this frame."
        vision_input_hash = hashlib.sha256(json.dumps(
            {
                "consent_id": consent_id,
                "source": source,
                "sequence_number": sequence_number,
                "captured_at": captured_at,
                "content_hash": digest,
                "content_type": content_type,
                "width": actual_width,
                "height": actual_height,
                "prompt_hash": hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        claim = self._claim_turn(
            session_id=session.session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            generation=generation,
            request_hash=self._turn_request_hash("image.frame", vision_input_hash),
            retry_of_turn_id=retry_of_turn_id,
        )
        if not claim.first_claim:
            return {"replayed": True, "turn_status": claim.status}
        try:
            staged = self.vision.accept_frame(
                session_id=session.session_id,
                device_id=device_id,
                consent_id=consent_id,
                source=source,
                sequence_number=sequence_number,
                captured_at=captured_at,
                content_type=content_type,
                raw=raw,
                declared_width=actual_width,
                declared_height=actual_height,
                prompt=normalized_prompt,
                turn_id=turn_id,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            try:
                self.turn_ledger.fail(
                    session_id=session.session_id,
                    turn_id=turn_id,
                    correlation_id=correlation_id,
                    generation=generation,
                    failure_code=type(exc).__name__,
                )
            except TurnClaimConflict:
                pass
            raise
        frame_id = staged["frame_id"]
        self.event_bus.emit(
            EventType.BROWSER_SENSE_VISION_FRAME_ACCEPTED,
            actor="aether.browser-senses",
            payload={
                key: value
                for key, value in staged.items()
                if key != "_working_path"
            },
            correlation_id=correlation_id,
        )
        adapter = DirectTextSenseAdapter(adapter_id="sense.browser-vision")
        data_url = f"{content_type};base64,{data_base64}"
        result: dict[str, Any] | None = None
        outcome = "failed"
        provider_id: str | None = None
        model_id: str | None = None
        try:
            result = await self._execute_claimed_turn(
                session_id=session.session_id,
                turn_id=turn_id,
                correlation_id=correlation_id,
                generation=generation,
                adapter=adapter,
                perception=Perception(
                    modality="image.frame",
                    content={"prompt": normalized_prompt, "image_data_url": f"data:{data_url}"},
                    source=f"browser:{session.session_id}",
                    metadata={
                        "channel": "browser",
                        "session_id": f"browser:{session.session_id}",
                        "response_modality": "text",
                        "capability": "vision",
                        "browser_sense_session_id": session.session_id,
                        "vision_frame_id": frame_id,
                        "vision_consent_id": consent_id,
                        "vision_source": source,
                        "vision_sequence_number": sequence_number,
                        "media_content_hash": digest,
                        "media_byte_count": len(raw),
                        "media_content_type": content_type,
                        "turn_id": turn_id,
                        "turn_generation": generation,
                    },
                    correlation_id=correlation_id,
                ),
                input_modality="image.frame",
                output_modality=None,
                transcript_hash=None,
                vision_frame_id=frame_id,
                actor="aether.browser-senses",
                metadata={
                    "retry_of_turn_id": retry_of_turn_id,
                    "vision_consent_id": consent_id,
                    "vision_source": source,
                    "vision_sequence_number": sequence_number,
                },
            )
            outcome = str(result["turn_status"]["state"])
            provider_id = result["turn"].get("provider_id")
            model_id = result["turn"].get("model_id")
        finally:
            raw = b""
            data_base64 = ""
            deleted = self.vision.delete_frame(frame_id, reason="vision-turn-terminal")
            receipt = VisionFrameReceipt(
                frame_id=deleted["frame_id"],
                session_id=deleted["session_id"],
                consent_id=deleted["consent_id"],
                source=BrowserSenseConsentSource(deleted["source"]),
                sequence_number=deleted["sequence_number"],
                content_hash=deleted["content_hash"],
                byte_count=deleted["byte_count"],
                content_type=deleted["content_type"],
                width=deleted["width"],
                height=deleted["height"],
                captured_at=deleted["captured_at"],
                accepted_at=deleted["accepted_at"],
                ephemeral_handle=deleted["ephemeral_handle"],
                prompt_hash=deleted["prompt_hash"],
                deletion_outcome=deleted["deletion_outcome"],
                deleted_at=deleted["deleted_at"],
                deletion_reason=deleted["deletion_reason"],
                turn_id=deleted["turn_id"],
                correlation_id=deleted["correlation_id"],
                outcome=outcome,
                provider_id=provider_id,
                model_id=model_id,
                metadata={"transport": BrowserSenseTransport.HTTP_KEYFRAME.value},
            )
            self.store.record_frame(receipt)
            self.event_bus.emit(
                EventType.BROWSER_SENSE_VISION_FRAME_DELETED,
                actor="aether.browser-senses",
                payload=asdict(receipt),
                correlation_id=correlation_id,
            )
        if result is None:
            raise RuntimeError("vision turn completed without a result")
        result["frame"] = asdict(receipt)
        return result

    def turn_status(self, token: str, turn_id: str) -> dict[str, Any]:
        session = self.authenticate(token)
        return self.turn_ledger.status(session_id=session.session_id, turn_id=turn_id)

    def interrupt_turn(
        self,
        token: str,
        *,
        turn_id: str,
        correlation_id: str,
        previous_generation: int,
        next_generation: int,
        reason: str,
        delivered_audio_ms: int | None,
        browser_audio_stopped: bool = False,
        livekit_control_sent: bool = False,
        provider_cancel_supported: bool = False,
        provider_cancelled: bool = False,
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        return self._interrupt_session_turn(
            session_id=session.session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            previous_generation=previous_generation,
            next_generation=next_generation,
            reason=reason,
            delivered_audio_ms=delivered_audio_ms,
            browser_audio_stopped=browser_audio_stopped,
            livekit_control_sent=livekit_control_sent,
            provider_cancel_supported=provider_cancel_supported,
            provider_cancelled=provider_cancelled,
            actor="aether.browser-senses",
        )

    def interrupt_worker_turn(
        self,
        *,
        room_name: str,
        turn_id: str,
        correlation_id: str,
        previous_generation: int,
        next_generation: int,
        reason: str,
        delivered_audio_ms: int | None,
        provider_cancel_supported: bool,
        provider_cancelled: bool,
        livekit_control_sent: bool = False,
    ) -> dict[str, Any]:
        session = self.store.get_session_by_room(room_name)
        return self._interrupt_session_turn(
            session_id=session.session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            previous_generation=previous_generation,
            next_generation=next_generation,
            reason=reason,
            delivered_audio_ms=delivered_audio_ms,
            browser_audio_stopped=False,
            livekit_control_sent=livekit_control_sent,
            provider_cancel_supported=provider_cancel_supported,
            provider_cancelled=provider_cancelled,
            actor="aether.livekit-worker",
        )

    def _interrupt_session_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        previous_generation: int,
        next_generation: int,
        reason: str,
        delivered_audio_ms: int | None,
        browser_audio_stopped: bool,
        livekit_control_sent: bool,
        provider_cancel_supported: bool,
        provider_cancelled: bool,
        actor: str,
    ) -> dict[str, Any]:
        interruption_reason = BrowserSenseInterruptionReason(reason)
        active = self._active_turns.get((session_id, turn_id))
        cognition_cancelled = bool(active and active[0] == previous_generation)
        payload = self.turn_ledger.interrupt(
            session_id=session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            previous_generation=previous_generation,
            next_generation=next_generation,
            reason=interruption_reason.value,
            provider_cancel_supported=provider_cancel_supported,
            provider_cancelled=provider_cancelled,
            delivered_audio_ms=delivered_audio_ms,
            upstream_cancelled=cognition_cancelled,
            browser_audio_stopped=browser_audio_stopped,
            livekit_control_sent=livekit_control_sent,
        )
        if cognition_cancelled:
            active[1].cancel()
        receipt = BrowserSenseInterruptionReceipt(
            receipt_id=payload["receipt_id"],
            session_id=session_id,
            turn_id=turn_id,
            reason=interruption_reason,
            requested_at=payload["requested_at"],
            audio_silent_at=payload["audio_silent_at"],
            previous_generation=previous_generation,
            next_generation=next_generation,
            delivered_audio_ms=delivered_audio_ms,
            provider_cancel_supported=bool(payload["provider_cancel_supported"]),
            provider_cancelled=bool(payload["provider_cancelled"]),
            late_result_disposition=BrowserSenseLateResultDisposition(
                payload["late_result_disposition"]
            ),
            metadata={
                "browser_audio_stopped": bool(payload["browser_audio_stopped"]),
                "livekit_control_sent": bool(payload["livekit_control_sent"]),
                "cognition_cancelled": cognition_cancelled,
            },
        )
        event_payload = asdict(receipt)
        self.event_bus.emit(
            EventType.BROWSER_SENSE_TURN_INTERRUPTED,
            actor=actor,
            payload=event_payload,
            correlation_id=correlation_id,
        )
        return payload

    def status(self) -> dict[str, Any]:
        return {
            "policy_id": "aether.browser-senses.v1",
            "contract_version": SENSES_V1_CONTRACT_VERSION,
            "required_runtime_profile": BrowserSenseRuntimeProfile.GOVERNED_PIPELINE.value,
            "livekit": self.livekit_issuer.status(),
            "maximum_frame_bytes": self.maximum_frame_bytes,
            "vision": {
                "consent_lease_seconds": BOUNDED_CONSENT_LEASE_SECONDS,
                "capture_interval_seconds": BOUNDED_CAPTURE_INTERVAL_SECONDS,
                "orphan_maximum_age_seconds": ORPHAN_FRAME_MAX_AGE_SECONDS,
                "continuous_video_transmission": False,
                "startup_orphan_frames_swept": self.startup_orphan_frames_swept,
                **self.vision.counts(),
            },
            "default_session_ttl_seconds": self.default_ttl_seconds,
            "store": self.store.status(),
            "turn_ledger": self.turn_ledger.counts(),
            "capabilities": [item.value for item in BrowserSenseCapability],
            "browser_requirements": {"secure_context": True, "permission_required": True},
        }

    @staticmethod
    def _session_dict(session: BrowserSenseSession) -> dict[str, Any]:
        data = asdict(session)
        data["capabilities"] = [item.value for item in session.capabilities]
        data["transports"] = [item.value for item in session.transports]
        data["state"] = session.state.value
        data["runtime_profile"] = session.runtime_profile.value if session.runtime_profile else None
        data.pop("token_hash", None)
        return data
