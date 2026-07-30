"""Configured OpenAI-compatible model provider for Aether Gateway."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
import yaml

from aether.contracts.actions import ActionProposal, ActionRisk, ActionScope, ActionTarget
from aether.contracts.llm import ModelProvider, ModelRequest, ModelResponse
from aether.resilience import ProviderErrorSignal
from aether.resilience.runtime import (
    ProviderProfile,
    ProviderRuntimeStateStore,
    ResilientProviderRouter,
)


class ModelInvocationError(RuntimeError):
    def __init__(self, message: str, *, failures: tuple[str, ...] = ()) -> None:
        self.failures = failures
        super().__init__(message)


class ConfiguredModelProvider(ModelProvider):
    def __init__(
        self,
        config_path: Path | None = None,
        *,
        timeout_seconds: int = 120,
        resilience_store: ProviderRuntimeStateStore | None = None,
        clock=time.time,
    ) -> None:
        self.config_path = config_path or Path(__file__).with_name("llm_providers.yaml")
        self.timeout_seconds = timeout_seconds
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        self.providers = self.config.get("providers", {})
        self.routing = self.config.get("routing", {})
        self.clock = clock
        self.resilience_store = resilience_store
        if self.resilience_store is None and self._resilience_enabled():
            home = Path(os.environ.get("AETHER_HOME") or Path.home() / ".aether")
            self.resilience_store = ProviderRuntimeStateStore(
                home / "runtime" / "provider-resilience.sqlite3"
            )

    @property
    def provider_id(self) -> str:
        return "gateway.configured-model-router"

    async def supports(self, capability: str) -> bool:
        return capability in {"reason", "plan", "critic", "coding", "vision"}

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        return await asyncio.to_thread(self.invoke_sync, request)

    def invoke_sync(self, request: ModelRequest) -> ModelResponse:
        preferred = str(request.constraints.get("preferred_model") or "").strip()
        primary = preferred or str(self.routing.get("default_fuel") or "").strip()
        if not primary:
            raise ModelInvocationError("No default model route configured")
        routes = []
        for route in [primary, *[str(item) for item in self.routing.get("fallback_chain", [])]]:
            if route and route not in routes:
                routes.append(route)
        if self.resilience_store is not None:
            return self._invoke_resilient(routes, request)
        failures = []
        for route in routes:
            try:
                return self._invoke_route(route, request)
            except Exception as exc:
                failures.append(f"{route}: {type(exc).__name__}: {exc}")
        raise ModelInvocationError(
            "All model routes failed: " + " | ".join(failures),
            failures=tuple(failures),
        )

    def _resilience_enabled(self) -> bool:
        configured = (self.routing.get("resilience") or {}).get("enabled")
        raw = os.environ.get("AETHER_PROVIDER_RESILIENCE_ENABLED")
        if raw is not None:
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(configured)

    def _invoke_resilient(
        self, routes: list[str], request: ModelRequest
    ) -> ModelResponse:
        route_by_provider: dict[str, str] = {}
        profiles: list[ProviderProfile] = []
        resilience = self.routing.get("resilience") or {}
        defaults = resilience.get("defaults") or {}
        provider_overrides = resilience.get("providers") or {}
        for priority, route in enumerate(routes, start=1):
            if "/" not in route:
                raise ValueError("model route must use provider/model format")
            provider_id = route.split("/", 1)[0]
            route_by_provider.setdefault(provider_id, route)
        for priority, provider_id in enumerate(route_by_provider, start=1):
            override = provider_overrides.get(provider_id) or {}
            profiles.append(
                ProviderProfile(
                    provider_id=provider_id,
                    priority=priority,
                    capabilities=frozenset(
                        override.get("capabilities")
                        or defaults.get("capabilities")
                        or {"reason", "plan", "critic", "coding", "vision"}
                    ),
                    daily_limit=int(
                        override.get("daily_request_limit")
                        or defaults.get("daily_request_limit")
                        or 100
                    ),
                    concurrency_limit=int(
                        override.get("concurrency_limit")
                        or defaults.get("concurrency_limit")
                        or 2
                    ),
                    failure_threshold=int(
                        override.get("failure_threshold")
                        or defaults.get("failure_threshold")
                        or 3
                    ),
                    cooldown_seconds=float(
                        override.get("cooldown_seconds")
                        or defaults.get("cooldown_seconds")
                        or 60
                    ),
                    data_policy_tags=frozenset(
                        override.get("data_policy_tags")
                        or defaults.get("data_policy_tags")
                        or {"cloud"}
                    ),
                    enabled=bool(override.get("enabled", True)),
                )
            )
        assert self.resilience_store is not None
        router = ResilientProviderRouter(
            profiles, self.resilience_store, clock=self.clock
        )
        failures: list[str] = []

        def operation(provider_id: str) -> ModelResponse:
            route = route_by_provider[provider_id]
            try:
                return self._invoke_route(route, request)
            except Exception as error:
                failures.append(f"{route}: {type(error).__name__}: {error}")
                raise

        try:
            return router.invoke(
                capability=request.capability,
                allowed_data_policy_tags=set(
                    request.constraints.get("allowed_data_policy_tags") or {"cloud"}
                ),
                operation=operation,
                error_signal=self._error_signal,
            )
        except Exception as error:
            raise ModelInvocationError(
                "All eligible model routes failed: " + " | ".join(failures),
                failures=tuple(failures),
            ) from error

    @staticmethod
    def _error_signal(error: Exception) -> ProviderErrorSignal:
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        retry_after = None
        if response is not None:
            raw = getattr(response, "headers", {}).get("Retry-After")
            try:
                retry_after = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                retry_after = None
        return ProviderErrorSignal(
            status_code=status_code,
            error_code=str(getattr(error, "error_code", "")),
            message=str(error),
            retry_after_seconds=retry_after,
            exception_name=type(error).__name__,
        )

    def _invoke_route(self, route: str, request: ModelRequest) -> ModelResponse:
        if "/" not in route:
            raise ValueError("model route must use provider/model format")
        provider_name, model_name = route.split("/", 1)
        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"unknown provider: {provider_name}")
        base_url = str(provider.get("base_url") or "").strip()
        api_key_env = str(provider.get("api_key_env") or "").strip()
        api_key = os.environ.get(api_key_env)
        if not base_url:
            raise ValueError(f"provider {provider_name} has no base_url")
        if not api_key:
            raise RuntimeError(f"missing API key environment variable {api_key_env}")

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [dict(message) for message in request.messages],
            "temperature": float(request.constraints.get("temperature", 0.2)),
        }
        max_tokens = request.constraints.get("max_tokens")
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)

        capability_map: dict[str, dict[str, Any]] = {}
        capabilities = request.constraints.get("action_capabilities") or []
        if capabilities:
            tools = []
            for raw in capabilities:
                item = dict(raw)
                target = str(item.get("target"))
                operation = str(item.get("operation"))
                name = self._function_name(target, operation)
                capability_map[name] = item
                tools.append({"type": "function", "function": {
                    "name": name,
                    "description": str(item.get("description") or f"Governed {target} action {operation}"),
                    "parameters": item.get("input_schema") or {"type": "object"},
                }})
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response = requests.post(base_url, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("provider response contained no choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        proposals = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            capability = capability_map.get(name)
            if capability is None:
                raise RuntimeError(f"provider requested undeclared action capability: {name}")
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid action arguments for {name}: {exc}") from exc
            scopes = tuple(ActionScope(str(scope)) for scope in capability.get("required_scopes") or [])
            target = ActionTarget(str(capability["target"]))
            proposals.append(ActionProposal(
                target=target,
                operation=str(capability["operation"]),
                arguments=arguments,
                required_scopes=scopes,
                reason=str(content).strip() or f"Model requested governed action {name}",
                risk=ActionRisk.LOW if set(scopes).issubset({ActionScope.READ, ActionScope.EXECUTE}) else ActionRisk.MEDIUM,
                reversible=bool(capability.get("reversible", True)),
                correlation_id=request.correlation_id,
                metadata={
                    "provider_tool_call_id": call.get("id"),
                    "runtime_id": str(capability.get("routing_key") or "default"),
                } if target == ActionTarget.RUNTIME else {"provider_tool_call_id": call.get("id")},
            ))
        if not str(content).strip() and not proposals:
            raise RuntimeError("provider response contained neither message content nor tool calls")
        usage = data.get("usage") or {}
        return ModelResponse(content, provider_name, model_name, {"route": route, "usage": usage, "request_id": response.headers.get("x-request-id")}, tuple(proposals))

    @staticmethod
    def _function_name(target: str, operation: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", operation)
        return f"{target}__{safe}"[:64]
