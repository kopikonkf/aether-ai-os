"""LiveKit voice worker that delegates every cognitive turn to Aether Gateway.

The LiveKit Agents SDK owns media transport, VAD, STT, turn handling, and TTS.
Aether owns identity, cognition, memory, governance, tools, and runtime routing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable

import requests


TURN_CONTROL_TOPIC = "aether.senses.turn-control.v1"
TURN_STATE_TOPIC = "aether.senses.turn-state.v1"
TURN_CONTROL_FIELDS = frozenset({
    "type",
    "turn_id",
    "correlation_id",
    "previous_generation",
    "next_generation",
    "reason",
})


@dataclass(frozen=True)
class LiveKitTurnGeneration:
    turn_id: str
    correlation_id: str
    generation: int = 0
    interrupted: bool = False
    reason: str | None = None


class LiveKitTurnCoordinator:
    def __init__(self) -> None:
        self._active: LiveKitTurnGeneration | None = None
        self._interruption: tuple[LiveKitTurnGeneration, LiveKitTurnGeneration] | None = None

    @property
    def active(self) -> LiveKitTurnGeneration | None:
        return self._active

    def begin(self) -> LiveKitTurnGeneration:
        self._active = LiveKitTurnGeneration(
            turn_id=f"turn-{uuid.uuid4()}",
            correlation_id=f"corr-{uuid.uuid4()}",
        )
        self._interruption = None
        return self._active

    def accepts(self, turn: LiveKitTurnGeneration) -> bool:
        return bool(self._active == turn and not turn.interrupted)

    def interrupt(self, reason: str) -> tuple[LiveKitTurnGeneration, LiveKitTurnGeneration] | None:
        if self._active is None:
            return None
        if self._interruption is not None:
            return self._interruption
        previous = self._active
        self._active = replace(
            previous,
            generation=previous.generation + 1,
            interrupted=True,
            reason=reason,
        )
        self._interruption = (previous, self._active)
        return self._interruption


def turn_state_payload(
    turn: LiveKitTurnGeneration,
    state: str,
    *,
    receipt_id: str | None = None,
    retry_of_turn_id: str | None = None,
) -> dict[str, Any]:
    if state not in {"accepted", "response-ready", "completed", "interrupted", "failed"}:
        raise ValueError("unknown LiveKit turn state")
    if state in {"completed", "interrupted"} and not str(receipt_id or "").strip():
        raise ValueError("terminal LiveKit turn state requires a receipt ID")
    return {
        "type": "turn-state",
        "state": state,
        "turn_id": turn.turn_id,
        "correlation_id": turn.correlation_id,
        "generation": turn.generation,
        "receipt_id": receipt_id,
        "retry_of_turn_id": retry_of_turn_id,
    }


def parse_turn_control(data: bytes, topic: str | None) -> dict[str, Any] | None:
    if topic != TURN_CONTROL_TOPIC or len(data) > 2048:
        return None
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != TURN_CONTROL_FIELDS:
        return None
    if payload.get("type") != "interrupt":
        return None
    if payload.get("reason") not in {
        "user_barge_in",
        "explicit_stop",
        "competing_input",
        "disconnect",
        "suspend",
    }:
        return None
    if not all(str(payload.get(name) or "").strip() for name in ("turn_id", "correlation_id")):
        return None
    previous = payload.get("previous_generation")
    next_generation = payload.get("next_generation")
    if (
        isinstance(previous, bool)
        or not isinstance(previous, int)
        or previous < 0
        or next_generation != previous + 1
    ):
        return None
    return payload


@dataclass(frozen=True)
class LiveKitWorkerConfig:
    gateway_url: str
    worker_token: str
    agent_name: str
    stt_model: str
    stt_language: str
    tts_model: str
    tts_voice: str
    stt_fallback_models: tuple[str, ...]
    tts_fallback_models: tuple[str, ...]
    tts_fallback_voices: tuple[str, ...]
    greeting: str
    turn_detector: str

    @classmethod
    def from_env(cls) -> "LiveKitWorkerConfig":
        return cls(
            gateway_url=str(os.environ.get("AETHER_GATEWAY_URL") or "http://127.0.0.1:8000").rstrip("/"),
            worker_token=str(os.environ.get("AETHER_SENSE_WORKER_TOKEN") or ""),
            agent_name=str(os.environ.get("LIVEKIT_AGENT_NAME") or "aether-sense"),
            stt_model=str(os.environ.get("AETHER_STT_MODEL") or "deepgram/nova-3"),
            stt_language=str(os.environ.get("AETHER_STT_LANGUAGE") or "multi"),
            tts_model=str(os.environ.get("AETHER_TTS_MODEL") or "cartesia/sonic-3"),
            tts_voice=str(os.environ.get("AETHER_TTS_VOICE") or "794f9389-aac1-45b6-b726-9d9369183238"),
            stt_fallback_models=_csv_env("AETHER_STT_FALLBACK_MODELS"),
            tts_fallback_models=_csv_env("AETHER_TTS_FALLBACK_MODELS"),
            tts_fallback_voices=_csv_env("AETHER_TTS_FALLBACK_VOICES"),
            greeting=str(os.environ.get("AETHER_SENSE_GREETING") or "Saya Aether. Saya mendengarkan."),
            turn_detector=str(os.environ.get("AETHER_TURN_DETECTOR") or "multilingual"),
        )

    def readiness(self) -> dict[str, Any]:
        livekit_env = {name: bool(os.environ.get(name)) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")}
        try:
            import livekit.agents  # noqa: F401
            import livekit.api  # noqa: F401
            sdk_ready = True
        except ModuleNotFoundError:
            sdk_ready = False
        return {
            "config": {**asdict(self), "worker_token": "<configured>" if self.worker_token else ""},
            "livekit_environment": livekit_env,
            "livekit_sdk_ready": sdk_ready,
            "ready": bool(all(livekit_env.values()) and sdk_ready and self.worker_token),
            "fallback": {
                "stt_models": list(self.stt_fallback_models),
                "tts_models": list(self.tts_fallback_models),
                "tts_voice_count": len(self.tts_fallback_voices),
                "configured": bool(self.stt_fallback_models or self.tts_fallback_models),
            },
        }

    def stt_fallback(self) -> list[dict[str, str]]:
        return [{"model": model} for model in self.stt_fallback_models]

    def tts_fallback(self) -> list[dict[str, str]]:
        if self.tts_fallback_voices and len(self.tts_fallback_voices) != len(
            self.tts_fallback_models
        ):
            raise ValueError(
                "AETHER_TTS_FALLBACK_VOICES must align with AETHER_TTS_FALLBACK_MODELS"
            )
        voices = self.tts_fallback_voices or tuple("" for _ in self.tts_fallback_models)
        return [
            {"model": model, "voice": voice}
            for model, voice in zip(self.tts_fallback_models, voices)
        ]


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for value in str(os.environ.get(name) or "").split(",")
        if value.strip()
    )


class AetherGatewayVoiceClient:
    def __init__(self, config: LiveKitWorkerConfig, *, timeout_seconds: int = 120) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def respond(
        self,
        *,
        room_name: str,
        participant_identity: str,
        text: str,
        turn: LiveKitTurnGeneration,
    ) -> dict[str, Any]:
        response = requests.post(
            f"{self.config.gateway_url}/api/browser-senses/worker/chat",
            headers={"Authorization": f"Bearer {self.config.worker_token}"},
            json={
                "room_name": room_name,
                "participant_identity": participant_identity,
                "text": text,
                "turn_id": turn.turn_id,
                "correlation_id": turn.correlation_id,
                "generation": turn.generation,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return dict(response.json())

    def interrupt(
        self,
        *,
        room_name: str,
        previous: LiveKitTurnGeneration,
        interrupted: LiveKitTurnGeneration,
        provider_cancel_supported: bool,
        provider_cancelled: bool,
        livekit_control_sent: bool = False,
    ) -> dict[str, Any]:
        response = requests.post(
            (
                f"{self.config.gateway_url}/api/browser-senses/worker/turns/"
                f"{previous.turn_id}/interrupt"
            ),
            headers={"Authorization": f"Bearer {self.config.worker_token}"},
            json={
                "room_name": room_name,
                "correlation_id": previous.correlation_id,
                "previous_generation": previous.generation,
                "next_generation": interrupted.generation,
                "reason": interrupted.reason,
                "delivered_audio_ms": None,
                "livekit_control_sent": livekit_control_sent,
                "browser_audio_stopped": False,
                "provider_cancel_supported": provider_cancel_supported,
                "provider_cancelled": provider_cancelled,
            },
            timeout=min(self.timeout_seconds, 15),
        )
        response.raise_for_status()
        return dict(response.json())


def _latest_user_text(chat_ctx: Any) -> str:
    items = list(getattr(chat_ctx, "items", ()) or ())
    for item in reversed(items):
        if str(getattr(item, "role", "")) not in {"user", "ChatRole.USER"}:
            continue
        text = getattr(item, "text_content", None)
        if callable(text):
            text = text()
        if text:
            return str(text).strip()
        content = getattr(item, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for value in content:
                if isinstance(value, str):
                    parts.append(value)
                elif isinstance(value, dict) and value.get("text"):
                    parts.append(str(value["text"]))
            if parts:
                return " ".join(parts).strip()
    return ""


def run_livekit_worker(config: LiveKitWorkerConfig | None = None) -> None:
    config = config or LiveKitWorkerConfig.from_env()
    readiness = config.readiness()
    if not readiness["ready"]:
        raise RuntimeError("LiveKit worker is not ready: " + json.dumps(readiness, sort_keys=True))

    from livekit.agents import Agent, AgentServer, AgentSession, JobContext, ModelSettings, cli, inference
    from livekit.plugins import silero

    try:
        from livekit.agents import RoomOptions
    except ImportError:  # compatibility with SDK versions before unified RoomOptions
        RoomOptions = None  # type: ignore[assignment]

    try:
        from livekit.agents.inference import TurnDetector
    except ModuleNotFoundError:
        TurnDetector = None  # type: ignore[assignment]

    client = AetherGatewayVoiceClient(config)
    server = AgentServer()

    class AetherMindAgent(Agent):
        def __init__(
            self,
            *,
            room_name: str,
            participant_identity: str,
            notify_turn: Callable[[dict[str, Any]], Awaitable[None]],
        ) -> None:
            super().__init__(
                instructions=(
                    "Aether Gateway is the only cognitive authority. Do not answer from a secondary model. "
                    "Forward each completed user turn to Aether and speak the exact returned text."
                )
            )
            self.room_name = room_name
            self.participant_identity = participant_identity
            self.turns = LiveKitTurnCoordinator()
            self.notify_turn = notify_turn
            self.terminal_status: dict[str, Any] | None = None

        async def llm_node(self, chat_ctx: Any, tools: list[Any], model_settings: ModelSettings):
            del tools, model_settings
            text = _latest_user_text(chat_ctx)
            if not text:
                return
            turn = self.turns.begin()
            self.terminal_status = None
            await self.notify_turn(turn_state_payload(turn, "accepted"))
            try:
                result = await asyncio.to_thread(
                    client.respond,
                    room_name=self.room_name,
                    participant_identity=self.participant_identity,
                    text=text,
                    turn=turn,
                )
            except requests.RequestException:
                if not self.turns.accepts(turn):
                    return
                raise
            if not self.turns.accepts(turn):
                return
            status = dict(result.get("turn_status") or {})
            if (
                status.get("state") != "completed"
                or status.get("turn_id") != turn.turn_id
                or status.get("correlation_id") != turn.correlation_id
                or status.get("generation") != turn.generation
                or not status.get("terminal_receipt_id")
            ):
                raise RuntimeError("Aether Gateway returned an unbound voice turn result")
            self.terminal_status = status
            await self.notify_turn(turn_state_payload(
                turn,
                "response-ready",
                receipt_id=status["terminal_receipt_id"],
            ))
            reply = str(result.get("response") or "").strip()
            if not reply:
                raise RuntimeError("Aether Gateway returned no playable voice response")
            yield reply

        async def on_enter(self) -> None:
            if config.greeting:
                await self.session.say(config.greeting, add_to_chat_ctx=False)

    @server.rtc_session(agent_name=config.agent_name)
    async def aether_sense_session(ctx: JobContext) -> None:
        linked_identity = "browser-user"
        try:
            linked_identity = str(ctx.room.remote_participants and next(iter(ctx.room.remote_participants.values())).identity or linked_identity)
        except Exception:
            pass
        session_kwargs: dict[str, Any] = {
            "vad": silero.VAD.load(),
            "stt": inference.STT(
                config.stt_model,
                language=config.stt_language,
                fallback=config.stt_fallback() or None,
            ),
            "tts": inference.TTS(
                config.tts_model,
                voice=config.tts_voice,
                fallback=config.tts_fallback() or None,
            ),
        }
        if config.turn_detector == "multilingual" and TurnDetector is not None:
            session_kwargs["turn_detection"] = TurnDetector()
        session = AgentSession(**session_kwargs)

        async def notify_turn(payload: dict[str, Any]) -> None:
            try:
                encoded = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                await ctx.room.local_participant.publish_data(
                    encoded,
                    reliable=True,
                    destination_identities=[linked_identity],
                    topic=TURN_STATE_TOPIC,
                )
            except Exception:
                # Data-channel UI metadata must never become a secondary authority
                # or fail the cognitive/audio pipeline.
                return

        agent = AetherMindAgent(
            room_name=ctx.room.name,
            participant_identity=linked_identity,
            notify_turn=notify_turn,
        )

        async def interrupt_pipeline(reason: str, control: dict[str, Any] | None = None) -> None:
            current = agent.turns.active
            if current is None:
                return
            if control is not None and (
                control["turn_id"] != current.turn_id
                or control["correlation_id"] != current.correlation_id
                or control["previous_generation"] != current.generation
            ):
                return
            generations = agent.turns.interrupt(reason)
            if generations is None:
                return
            previous, interrupted = generations
            if control is not None and control["next_generation"] != interrupted.generation:
                return
            provider_cancel_supported = bool(
                getattr(session, "current_speech", None) is not None
                or str(getattr(session, "agent_state", "")) in {"thinking", "speaking"}
            )
            provider_cancelled = False
            if provider_cancel_supported:
                try:
                    await session.interrupt()
                    provider_cancelled = True
                except RuntimeError:
                    provider_cancelled = False
            try:
                receipt = await asyncio.to_thread(
                    client.interrupt,
                    room_name=ctx.room.name,
                    previous=previous,
                    interrupted=interrupted,
                    provider_cancel_supported=provider_cancel_supported,
                    provider_cancelled=provider_cancelled,
                    livekit_control_sent=control is not None,
                )
                await notify_turn(turn_state_payload(
                    interrupted,
                    "interrupted",
                    receipt_id=str(receipt["receipt_id"]),
                ))
            except requests.RequestException:
                # Audio is already stopped locally by AgentSession. Gateway
                # reconciliation remains unconfirmed and is never fabricated.
                return

        @session.on("user_state_changed")
        def on_user_state_changed(event: Any) -> None:
            if str(getattr(event, "new_state", "")) == "speaking":
                asyncio.create_task(interrupt_pipeline("user_barge_in"))

        previous_agent_state = ""

        @session.on("agent_state_changed")
        def on_agent_state_changed(event: Any) -> None:
            nonlocal previous_agent_state
            new_state = str(getattr(event, "new_state", ""))
            was_speaking = previous_agent_state == "speaking"
            previous_agent_state = new_state
            active = agent.turns.active
            status = agent.terminal_status
            if (
                was_speaking
                and new_state in {"listening", "idle"}
                and active is not None
                and not active.interrupted
                and status is not None
            ):
                asyncio.create_task(notify_turn(turn_state_payload(
                    active,
                    "completed",
                    receipt_id=str(status["terminal_receipt_id"]),
                )))

        @ctx.room.on("data_received")
        def on_data_received(packet: Any) -> None:
            participant = getattr(packet, "participant", None)
            if participant is not None and str(getattr(participant, "identity", "")) != linked_identity:
                return
            control = parse_turn_control(
                bytes(getattr(packet, "data", b"")),
                getattr(packet, "topic", None),
            )
            if control is not None:
                asyncio.create_task(interrupt_pipeline(control["reason"], control))

        start_kwargs: dict[str, Any] = {
            "agent": agent,
            "room": ctx.room,
        }
        if RoomOptions is not None:
            start_kwargs["room_options"] = RoomOptions(
                audio_input=True,
                audio_output=True,
                text_input=True,
                video_input=False,
            )
        await session.start(**start_kwargs)

    cli.run_app(server)


def main() -> int:
    args: list[str] = list(sys.argv[1:])
    env_file: str | None = None
    if "--env-file" in args:
        index = args.index("--env-file")
        if index + 1 >= len(args):
            print("error: --env-file requires a path", file=sys.stderr)
            return 2
        env_file = args[index + 1]
        del args[index:index + 2]
    if env_file:
        env_path = Path(env_file).expanduser()
        if not env_path.is_file():
            print(f"error: env-file not found: {env_path}", file=sys.stderr)
            return 2
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    config = LiveKitWorkerConfig.from_env()
    if len(args) == 0 or args[0] == "status":
        print(json.dumps(config.readiness(), indent=2))
        return 0 if config.readiness()["ready"] else 2
    run_livekit_worker(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
