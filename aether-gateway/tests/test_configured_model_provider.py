from __future__ import annotations

import asyncio
from pathlib import Path

from aether.contracts import ActionScope, ActionTarget, ModelRequest
from aether.resilience.runtime import ProviderRuntimeStateStore
from aether_gateway.providers import ConfiguredModelProvider


def test_configured_provider_resolves_route_and_returns_metadata(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        """
providers:
  demo:
    base_url: https://example.invalid/chat
    api_key_env: DEMO_API_KEY
routing:
  default_fuel: demo/model-a
  fallback_chain: []
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEMO_API_KEY", "secret")

    class Response:
        headers = {"x-request-id": "req-1"}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"total_tokens": 3},
            }

    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr("aether_gateway.providers.configured.requests.post", fake_post)
    provider = ConfiguredModelProvider(config, timeout_seconds=9)
    response = asyncio.run(
        provider.invoke(
            ModelRequest(
                capability="reason",
                messages=[{"role": "user", "content": "hi"}],
            )
        )
    )

    assert response.content == "hello"
    assert response.provider_id == "demo"
    assert response.model_id == "model-a"
    assert response.metadata["request_id"] == "req-1"
    assert captured["json"]["model"] == "model-a"
    assert captured["timeout"] == 9


def test_preferred_model_overrides_default_route(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        """
providers:
  demo:
    base_url: https://example.invalid/chat
    api_key_env: DEMO_API_KEY
routing:
  default_fuel: demo/default
  fallback_chain: []
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEMO_API_KEY", "secret")

    class Response:
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    models = []

    def fake_post(url, headers, json, timeout):
        models.append(json["model"])
        return Response()

    monkeypatch.setattr("aether_gateway.providers.configured.requests.post", fake_post)
    provider = ConfiguredModelProvider(config)
    response = provider.invoke_sync(
        ModelRequest(
            capability="reason",
            messages=[{"role": "user", "content": "hi"}],
            constraints={"preferred_model": "demo/preferred"},
        )
    )

    assert response.model_id == "preferred"
    assert models == ["preferred"]


def test_provider_normalizes_tool_calls_into_action_proposals(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "models.yaml"
    config.write_text("""
providers:
  demo:
    base_url: https://example.invalid/chat
    api_key_env: DEMO_API_KEY
routing:
  default_fuel: demo/model-a
  fallback_chain: []
""".strip(), encoding="utf-8")
    monkeypatch.setenv("DEMO_API_KEY", "secret")

    class Response:
        headers = {}
        def raise_for_status(self): return None
        def json(self):
            return {"choices": [{"message": {"content": "Need evidence", "tool_calls": [{
                "id": "call-1", "type": "function", "function": {"name": "tool__read", "arguments": "{\"path\": \"note.txt\"}"}
            }]}}]}

    captured = {}
    def fake_post(url, headers, json, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("aether_gateway.providers.configured.requests.post", fake_post)
    provider = ConfiguredModelProvider(config)
    response = provider.invoke_sync(ModelRequest(
        capability="reason",
        messages=[{"role": "user", "content": "check"}],
        constraints={"action_capabilities": [{
            "target": ActionTarget.TOOL, "operation": "read", "description": "read",
            "required_scopes": [ActionScope.READ], "reversible": True,
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
        }]},
    ))
    assert captured["tools"][0]["function"]["name"] == "tool__read"
    assert len(response.action_proposals) == 1
    proposal = response.action_proposals[0]
    assert proposal.target == ActionTarget.TOOL
    assert proposal.arguments["path"] == "note.txt"
    assert proposal.required_scopes == (ActionScope.READ,)


def test_cognition_router_uses_persistent_budget_and_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "models.yaml"
    config.write_text(
        """
providers:
  primary:
    base_url: https://primary.invalid/chat
    api_key_env: PRIMARY_KEY
  fallback:
    base_url: https://fallback.invalid/chat
    api_key_env: FALLBACK_KEY
routing:
  default_fuel: primary/model-a
  fallback_chain: [fallback/model-b]
  resilience:
    enabled: true
    defaults:
      daily_request_limit: 1
      concurrency_limit: 1
      failure_threshold: 1
      cooldown_seconds: 60
      data_policy_tags: [cloud]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRIMARY_KEY", "secret")
    monkeypatch.setenv("FALLBACK_KEY", "secret")

    class Response:
        headers = {}

        def __init__(self, status_code, content="ok"):
            self.status_code = status_code
            self._content = content

        def raise_for_status(self):
            if self.status_code >= 400:
                error = RuntimeError("quota exhausted")
                error.response = self
                error.error_code = "insufficient_quota"
                raise error

        def json(self):
            return {"choices": [{"message": {"content": self._content}}]}

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        return Response(429) if "primary" in url else Response(200, "fallback")

    monkeypatch.setattr("aether_gateway.providers.configured.requests.post", fake_post)
    store_path = tmp_path / "runtime" / "provider-resilience.sqlite3"
    provider = ConfiguredModelProvider(
        config,
        resilience_store=ProviderRuntimeStateStore(store_path),
        clock=lambda: 100.0,
    )
    response = provider.invoke_sync(
        ModelRequest(capability="reason", messages=[{"role": "user", "content": "hi"}])
    )

    assert response.content == "fallback"
    assert calls == [
        "https://primary.invalid/chat",
        "https://fallback.invalid/chat",
    ]
    reopened = ProviderRuntimeStateStore(store_path)
    assert reopened.path.is_file()
