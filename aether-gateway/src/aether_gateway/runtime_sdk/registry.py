"""Discovery registry for replaceable runtime adapters."""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from aether.contracts import RuntimeAdapter
from aether.contracts.coding_runtime import RuntimeDescriptor, RuntimeHealthStatus
from aether.contracts.event_types import EventType
from aether.events import EventBus

from .sdk import validate_runtime_adapter


class RuntimeAdapterRegistry:
    def __init__(self, *, event_bus: EventBus | None = None) -> None:
        self._adapters: dict[str, RuntimeAdapter] = {}
        self._descriptors: dict[str, RuntimeDescriptor] = {}
        self.event_bus = event_bus

    def register(self, adapter: RuntimeAdapter, descriptor: RuntimeDescriptor) -> None:
        validate_runtime_adapter(adapter, descriptor)
        if descriptor.routing_key in self._adapters:
            raise ValueError(f"runtime routing key already registered: {descriptor.routing_key}")
        if adapter.adapter_id != descriptor.adapter_id:
            raise ValueError("adapter ID does not match runtime descriptor")
        self._adapters[descriptor.routing_key] = adapter
        self._descriptors[descriptor.routing_key] = descriptor
        self._emit(EventType.RUNTIME_ADAPTER_DISCOVERED, {
            "routing_key": descriptor.routing_key, "adapter_id": descriptor.adapter_id,
            "capabilities": list(descriptor.capabilities), "features": list(descriptor.runtime_features),
        })

    def adapter(self, routing_key: str) -> RuntimeAdapter:
        try:
            return self._adapters[routing_key]
        except KeyError as exc:
            raise KeyError(f"unknown runtime routing key: {routing_key}") from exc

    def runtime_mapping(self) -> Mapping[str, RuntimeAdapter]:
        return dict(self._adapters)

    async def discover(self) -> Sequence[RuntimeDescriptor]:
        results: list[RuntimeDescriptor] = []
        for key, registered_descriptor in tuple(self._descriptors.items()):
            adapter = self._adapters[key]
            descriptor = registered_descriptor
            try:
                discover_descriptor = getattr(adapter, "discover_descriptor", None)
                if callable(discover_descriptor):
                    discovered = await discover_descriptor()
                    validate_runtime_adapter(adapter, discovered)
                    if discovered.routing_key != key:
                        raise ValueError("discovered runtime routing key differs from registered routing key")
                    descriptor = discovered
                    self._descriptors[key] = discovered
                health = dict(await adapter.health())
                ok = bool(health.get("ok", False))
                degraded = bool(health.get("degraded", False))
                status = RuntimeHealthStatus.HEALTHY if ok and not degraded else RuntimeHealthStatus.DEGRADED if ok else RuntimeHealthStatus.UNAVAILABLE
                updated = replace(descriptor, health_status=status, metadata={**dict(descriptor.metadata), "health": health})
            except Exception as exc:
                updated = replace(descriptor, health_status=RuntimeHealthStatus.UNAVAILABLE,
                                  metadata={**dict(descriptor.metadata), "health_error": f"{type(exc).__name__}: {exc}"})
            results.append(updated)
            self._emit(EventType.RUNTIME_HEALTH_CHECKED, {
                "routing_key": updated.routing_key, "adapter_id": updated.adapter_id,
                "health_status": updated.health_status.value,
            }, severity="info" if updated.health_status == RuntimeHealthStatus.HEALTHY else "warning")
        health_rank = {
            RuntimeHealthStatus.HEALTHY: 0,
            RuntimeHealthStatus.DEGRADED: 1,
            RuntimeHealthStatus.UNAVAILABLE: 2,
        }
        return tuple(sorted(results, key=lambda item: (health_rank[item.health_status], item.priority, item.adapter_id)))

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, severity: str = "info") -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type, actor="aether.runtime-sdk.registry", payload=dict(payload), severity=severity)
