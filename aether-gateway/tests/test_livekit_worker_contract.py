from __future__ import annotations

import pytest

from aether_gateway.browser_senses.worker import LiveKitWorkerConfig, _latest_user_text


class Item:
    role = "user"
    text_content = "  Halo Aether  "


class Context:
    items = [Item()]


def test_livekit_worker_is_import_safe_without_optional_sdk(monkeypatch):
    monkeypatch.delenv("LIVEKIT_URL", raising=False)
    config = LiveKitWorkerConfig.from_env()
    status = config.readiness()
    assert status["ready"] is False
    assert status["config"]["worker_token"] == ""
    assert _latest_user_text(Context()) == "Halo Aether"


def test_aether_gateway_llm_sentinel_is_pipeline_enabler():
    livekit = pytest.importorskip("livekit.agents")
    from aether_gateway.browser_senses.worker import run_livekit_worker

    # Sentinel lives inside run_livekit_worker's scope (lazy import pattern).
    # Reaching into a closure is not supported; instead we assert the code
    # path wiring exists by inspecting the source: the agent must pass
    # llm=AetherGatewayLLMSentinel() and the sentinel must subclass llm.LLM.
    import inspect

    src = inspect.getsource(run_livekit_worker)
    assert "class AetherGatewayLLMSentinel(llm.LLM):" in src
    assert "llm=AetherGatewayLLMSentinel()," in src
    assert livekit is not None
