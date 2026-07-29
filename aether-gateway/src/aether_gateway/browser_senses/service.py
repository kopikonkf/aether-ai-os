"""Secure browser-sense session service.

LiveKit transports media. Aether remains the identity, cognition, memory, and
approval authority. Browser session tokens are short-lived and distinct from
the operator token and LiveKit participant token.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import secrets
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from aether.browser_senses import BrowserSenseStore
from aether.contracts import (
    BrowserSenseCapability,
    BrowserSenseSession,
    BrowserSenseSessionState,
    BrowserSenseTransport,
    BrowserSenseTurnReceipt,
    BrowserMediaTrackReceipt,
    MediaTrackKind,
    EventType,
    Perception,
    VisionFrameReceipt,
)
from aether.events import EventBus
from aether.senses import SenseEventPath
from aether.utils.ids import new_id
from aether.utils.time import utc_now
from aether_gateway.adapters import DirectTextSenseAdapter


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
        self.sense_path = sense_path
        self.event_bus = event_bus
        self.token_codec = token_codec
        self.livekit_issuer = livekit_issuer or LiveKitTokenIssuer()
        self.maximum_frame_bytes = maximum_frame_bytes
        self.default_ttl_seconds = default_ttl_seconds

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
    ) -> dict[str, Any]:
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
            metadata={**dict(metadata or {}), "livekit_ready": bool(livekit.get("ready"))},
        )
        self.store.record_session(session)
        self.event_bus.emit(EventType.BROWSER_SENSE_SESSION_ISSUED, actor="aether.browser-senses", payload={
            "session_id": session.session_id,
            "room_name": session.room_name,
            "capabilities": [item.value for item in session.capabilities],
            "transports": [item.value for item in session.transports],
            "expires_at": session.expires_at,
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
        closed = self.store.transition_session(session.session_id, BrowserSenseSessionState.CLOSED, recorded_at=utc_now(), metadata={"close_reason": reason})
        self.event_bus.emit(EventType.BROWSER_SENSE_SESSION_CLOSED, actor="aether.browser-senses", payload={"session_id": closed.session_id, "reason": reason})
        return closed

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

    async def handle_text(self, token: str, text: str, *, modality: str = "browser.text") -> dict[str, Any]:
        session = self.authenticate(token)
        normalized = text.strip()
        if not normalized:
            raise ValueError("text must not be empty")
        adapter = DirectTextSenseAdapter(adapter_id="sense.browser")
        started = utc_now()
        trace = await self.sense_path.handle(adapter, Perception(
            modality=modality,
            content=normalized,
            source=f"browser:{session.session_id}",
            metadata={
                "channel": "browser",
                "session_id": f"browser:{session.session_id}",
                "response_modality": "text",
                "browser_sense_session_id": session.session_id,
            },
        ))
        expression = adapter.expressions[-1]
        turn = BrowserSenseTurnReceipt(
            turn_id=new_id("sense-turn"), session_id=session.session_id,
            input_modality=modality, output_modality=expression.modality,
            transcript_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            vision_frame_id=None, correlation_id=trace.correlation_id,
            started_at=started, completed_at=utc_now(),
            provider_id=expression.metadata.get("provider_id"), model_id=expression.metadata.get("model_id"),
        )
        self.store.record_turn(turn)
        self.event_bus.emit(EventType.BROWSER_SENSE_TURN_COMPLETED, actor="aether.browser-senses", payload={
            "turn_id": turn.turn_id, "session_id": session.session_id, "input_modality": modality,
            "output_modality": expression.modality, "correlation_id": trace.correlation_id,
        })
        return {"response": expression.content, "expression": asdict(expression), "trace": asdict(trace), "turn": asdict(turn)}

    async def handle_worker_transcript(
        self,
        *,
        room_name: str,
        participant_identity: str,
        text: str,
    ) -> dict[str, Any]:
        try:
            session = self.store.get_session_by_room(room_name)
            browser_session_id = session.session_id
        except KeyError:
            browser_session_id = self._safe_identity(room_name, "livekit-room")
        normalized = text.strip()
        if not normalized:
            raise ValueError("transcript must not be empty")
        adapter = DirectTextSenseAdapter(adapter_id="sense.livekit-worker")
        started = utc_now()
        trace = await self.sense_path.handle(adapter, Perception(
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
            },
        ))
        expression = adapter.expressions[-1]
        turn = BrowserSenseTurnReceipt(
            turn_id=new_id("sense-turn"), session_id=browser_session_id,
            input_modality="audio.transcript", output_modality="audio.speech",
            transcript_hash=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            vision_frame_id=None, correlation_id=trace.correlation_id,
            started_at=started, completed_at=utc_now(),
            provider_id=expression.metadata.get("provider_id"), model_id=expression.metadata.get("model_id"),
            metadata={"transport": BrowserSenseTransport.LIVEKIT.value, "participant_identity": participant_identity},
        )
        try:
            self.store.record_turn(turn)
        except sqlite3.IntegrityError:
            pass
        self.event_bus.emit(EventType.BROWSER_SENSE_TURN_COMPLETED, actor="aether.livekit-worker", payload={
            "turn_id": turn.turn_id, "session_id": browser_session_id, "input_modality": "audio.transcript",
            "output_modality": "audio.speech", "correlation_id": trace.correlation_id,
        })
        return {"response": expression.content, "expression": asdict(expression), "trace": asdict(trace), "turn": asdict(turn)}

    async def handle_vision(
        self,
        token: str,
        *,
        data_base64: str,
        content_type: str,
        prompt: str,
        width: int | None = None,
        height: int | None = None,
    ) -> dict[str, Any]:
        session = self.authenticate(token)
        if BrowserSenseCapability.CAMERA not in session.capabilities:
            raise BrowserSenseAuthError("camera capability was not granted")
        try:
            raw = base64.b64decode(data_base64, validate=True)
        except Exception as exc:
            raise ValueError("invalid base64 vision frame") from exc
        if not raw or len(raw) > self.maximum_frame_bytes:
            raise ValueError(f"vision frame must be 1..{self.maximum_frame_bytes} bytes")
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported vision frame content type")
        digest = hashlib.sha256(raw).hexdigest()
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
        frame_id = new_id("vision-frame")
        session_dir = self.frames_root / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / f"{frame_id}{suffix}"
        path.write_bytes(raw)
        receipt = VisionFrameReceipt(
            frame_id=frame_id, session_id=session.session_id, content_hash=digest,
            byte_count=len(raw), content_type=content_type, width=width, height=height,
            observed_at=utc_now(), storage_reference=str(path.relative_to(self.root)),
            prompt=prompt.strip() or "Describe only what is materially visible in this frame.",
            metadata={"transport": BrowserSenseTransport.HTTP_KEYFRAME.value},
        )
        self.store.record_frame(receipt)
        self.event_bus.emit(EventType.BROWSER_SENSE_VISION_FRAME_RECORDED, actor="aether.browser-senses", payload={
            "frame_id": frame_id, "session_id": session.session_id, "content_hash": digest,
            "byte_count": len(raw), "content_type": content_type,
        })
        adapter = DirectTextSenseAdapter(adapter_id="sense.browser-vision")
        started = utc_now()
        data_url = f"{content_type};base64,{data_base64}"
        trace = await self.sense_path.handle(adapter, Perception(
            modality="image.frame",
            content={"prompt": receipt.prompt, "image_data_url": f"data:{data_url}"},
            source=f"browser:{session.session_id}",
            metadata={
                "channel": "browser",
                "session_id": f"browser:{session.session_id}",
                "response_modality": "text",
                "capability": "vision",
                "browser_sense_session_id": session.session_id,
                "vision_frame_id": frame_id,
                "media_content_hash": digest,
                "media_byte_count": len(raw),
                "media_content_type": content_type,
            },
        ))
        expression = adapter.expressions[-1]
        turn = BrowserSenseTurnReceipt(
            turn_id=new_id("sense-turn"), session_id=session.session_id,
            input_modality="image.frame", output_modality=expression.modality,
            transcript_hash=None, vision_frame_id=frame_id, correlation_id=trace.correlation_id,
            started_at=started, completed_at=utc_now(),
            provider_id=expression.metadata.get("provider_id"), model_id=expression.metadata.get("model_id"),
        )
        self.store.record_turn(turn)
        return {"frame": asdict(receipt), "response": expression.content, "expression": asdict(expression), "trace": asdict(trace), "turn": asdict(turn)}

    def status(self) -> dict[str, Any]:
        return {
            "policy_id": "aether.browser-senses.v1",
            "livekit": self.livekit_issuer.status(),
            "maximum_frame_bytes": self.maximum_frame_bytes,
            "default_session_ttl_seconds": self.default_ttl_seconds,
            "store": self.store.status(),
            "capabilities": [item.value for item in BrowserSenseCapability],
            "browser_requirements": {"secure_context": True, "permission_required": True},
        }

    @staticmethod
    def _session_dict(session: BrowserSenseSession) -> dict[str, Any]:
        data = asdict(session)
        data["capabilities"] = [item.value for item in session.capabilities]
        data["transports"] = [item.value for item in session.transports]
        data["state"] = session.state.value
        data.pop("token_hash", None)
        return data
