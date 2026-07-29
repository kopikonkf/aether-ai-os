from __future__ import annotations

import asyncio

from aether.cognition import AetherCognitiveGateway, InMemoryConversationStore
from aether.contracts import (ActionCapability, ActionProposal, ActionResult, ActionScope, ActionTarget, ModelRequest, ModelResponse, Perception)


class FakeModelProvider:
    provider_id = "provider.fake"

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def supports(self, capability: str) -> bool:
        return True

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        user = request.messages[-1]["content"]
        return ModelResponse(
            content=f"reply:{user}",
            provider_id=self.provider_id,
            model_id="fake-v1",
            metadata={"verified": True},
        )


def test_gateway_routes_capability_and_preserves_session_context() -> None:
    provider = FakeModelProvider()
    store = InMemoryConversationStore(max_messages=8)
    gateway = AetherCognitiveGateway(provider, conversation_store=store, system_prompt="system")

    async def scenario():
        first = await gateway.respond(
            Perception(
                modality="telegram.text",
                content="hello",
                source="telegram:1",
                metadata={
                    "session_id": "telegram:1",
                    "chat_id": 1,
                    "preferred_model": "vendor/model",
                },
            )
        )
        second = await gateway.respond(
            Perception(
                modality="telegram.text",
                content="again",
                source="telegram:1",
                metadata={"session_id": "telegram:1", "chat_id": 1},
            )
        )
        return first, second, await store.get("telegram:1")

    first, second, history = asyncio.run(scenario())

    assert first.content == "reply:hello"
    assert first.metadata["provider_id"] == "provider.fake"
    assert first.metadata["model_id"] == "fake-v1"
    assert first.metadata["chat_id"] == 1
    assert provider.requests[0].constraints["preferred_model"] == "vendor/model"
    assert [message["role"] for message in provider.requests[1].messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert len(history) == 4
    assert second.target == "telegram:1"



def test_audio_transcript_defaults_to_speech_expression() -> None:
    provider = FakeModelProvider()
    gateway = AetherCognitiveGateway(provider)

    expression = asyncio.run(gateway.respond(Perception(
        modality="audio.transcript",
        content="Halo Aether",
        source="microphone",
        metadata={"session_id": "voice:founder"},
    )))

    assert expression.modality == "speech"
    assert expression.target == "microphone"


def test_explicit_response_modality_overrides_audio_default() -> None:
    provider = FakeModelProvider()
    gateway = AetherCognitiveGateway(provider)

    expression = asyncio.run(gateway.respond(Perception(
        modality="audio.transcript",
        content="Return as text",
        source="microphone",
        metadata={
            "session_id": "voice:founder",
            "response_modality": "text",
        },
    )))

    assert expression.modality == "text"

def test_gateway_clear_session_removes_short_term_context() -> None:
    provider = FakeModelProvider()
    store = InMemoryConversationStore()
    gateway = AetherCognitiveGateway(provider, conversation_store=store)

    async def scenario():
        perception = Perception(
            modality="http.text",
            content="hello",
            source="http:test",
            metadata={"session_id": "http:test"},
        )
        await gateway.respond(perception)
        await gateway.clear_session("http:test")
        return await store.get("http:test")

    assert asyncio.run(scenario()) == ()


def test_gateway_rejects_unsupported_modality() -> None:
    gateway = AetherCognitiveGateway(FakeModelProvider())

    try:
        asyncio.run(gateway.respond(Perception(modality="image", content="x", source="camera")))
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("expected ValueError")


class FakeActionExecutor:
    def __init__(self):
        self.calls = []

    async def capabilities(self):
        return [ActionCapability(ActionTarget.TOOL, "read", "read", (ActionScope.READ,), True, {"type": "object"})]

    async def execute(self, proposal, approval=None):
        self.calls.append(proposal)
        return ActionResult(proposal.action_id, True, "completed", output="evidence")


class ActionModelProvider:
    provider_id = "provider.action"

    def __init__(self):
        self.requests = []

    async def supports(self, capability):
        return True

    async def invoke(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return ModelResponse("I need evidence", self.provider_id, "action-v1", action_proposals=(
                ActionProposal(ActionTarget.TOOL, "read", {"path": "note.txt"}, (ActionScope.READ,), "Read evidence before answering", correlation_id=request.correlation_id),
            ))
        return ModelResponse("Evidence says yes.", self.provider_id, "action-v1")


def test_gateway_continues_cognition_after_governed_action():
    provider = ActionModelProvider()
    executor = FakeActionExecutor()
    gateway = AetherCognitiveGateway(provider, action_executor=executor)
    expression = asyncio.run(gateway.respond(Perception("text", "Check", "cli", correlation_id="corr-1")))
    assert expression.content == "Evidence says yes."
    assert len(provider.requests) == 2
    assert len(executor.calls) == 1
    assert provider.requests[0].constraints["action_capabilities"][0]["operation"] == "read"
    assert "Governed action results" in provider.requests[1].messages[-1]["content"]
    assert expression.metadata["action_results"][0]["status"] == "completed"

class VisionModelProvider:
    provider_id = "provider.vision"

    def __init__(self) -> None:
        self.request = None

    async def supports(self, capability: str) -> bool:
        return capability == "vision"

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        self.request = request
        return ModelResponse("I can see a whiteboard.", self.provider_id, "vision-v1")


def test_vision_frame_uses_multimodal_message_but_persists_only_prompt() -> None:
    provider = VisionModelProvider()
    store = InMemoryConversationStore()
    gateway = AetherCognitiveGateway(provider, conversation_store=store)
    image = "data:image/jpeg;base64," + "YWJj"

    expression = asyncio.run(gateway.respond(Perception(
        modality="image.frame",
        content={"prompt": "What is visible?", "image_data_url": image},
        source="browser:camera",
        metadata={"session_id": "browser:1", "capability": "vision"},
    )))
    history = asyncio.run(store.get("browser:1"))

    assert expression.content == "I can see a whiteboard."
    assert provider.request.capability == "vision"
    assert provider.request.messages[-1]["content"][1]["image_url"]["url"] == image
    assert history[0] == {"role": "user", "content": "What is visible?"}
    assert image not in str(history)
