"""LiveKit voice worker that delegates every cognitive turn to Aether Gateway.

The LiveKit Agents SDK owns media transport, VAD, STT, turn handling, and TTS.
Aether owns identity, cognition, memory, governance, tools, and runtime routing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class LiveKitWorkerConfig:
    gateway_url: str
    worker_token: str
    agent_name: str
    stt_model: str
    stt_language: str
    tts_model: str
    tts_voice: str
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
        }


class AetherGatewayVoiceClient:
    def __init__(self, config: LiveKitWorkerConfig, *, timeout_seconds: int = 120) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

    def respond(self, *, room_name: str, participant_identity: str, text: str) -> str:
        response = requests.post(
            f"{self.config.gateway_url}/api/browser-senses/worker/chat",
            headers={"Authorization": f"Bearer {self.config.worker_token}"},
            json={
                "room_name": room_name,
                "participant_identity": participant_identity,
                "text": text,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        reply = str(data.get("response") or "").strip()
        if not reply:
            raise RuntimeError("Aether Gateway returned an empty voice response")
        return reply


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
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
    except ModuleNotFoundError:
        MultilingualModel = None  # type: ignore[assignment]

    client = AetherGatewayVoiceClient(config)
    server = AgentServer()

    class AetherMindAgent(Agent):
        def __init__(self, *, room_name: str, participant_identity: str) -> None:
            super().__init__(
                instructions=(
                    "Aether Gateway is the only cognitive authority. Do not answer from a secondary model. "
                    "Forward each completed user turn to Aether and speak the exact returned text."
                )
            )
            self.room_name = room_name
            self.participant_identity = participant_identity

        async def llm_node(self, chat_ctx: Any, tools: list[Any], model_settings: ModelSettings):
            del tools, model_settings
            text = _latest_user_text(chat_ctx)
            if not text:
                return
            reply = await asyncio.to_thread(
                client.respond,
                room_name=self.room_name,
                participant_identity=self.participant_identity,
                text=text,
            )
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
            "stt": inference.STT(config.stt_model, language=config.stt_language),
            "tts": inference.TTS(config.tts_model, voice=config.tts_voice),
        }
        if config.turn_detector == "multilingual" and MultilingualModel is not None:
            session_kwargs["turn_detection"] = MultilingualModel()
        session = AgentSession(**session_kwargs)
        start_kwargs: dict[str, Any] = {
            "agent": AetherMindAgent(room_name=ctx.room.name, participant_identity=linked_identity),
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
    config = LiveKitWorkerConfig.from_env()
    if len(sys.argv) == 1 or sys.argv[1] == "status":
        print(json.dumps(config.readiness(), indent=2))
        return 0 if config.readiness()["ready"] else 2
    run_livekit_worker(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
