from __future__ import annotations

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
