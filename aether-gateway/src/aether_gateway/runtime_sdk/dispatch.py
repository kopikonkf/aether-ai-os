"""Private governed dispatcher that provides post-approval runtime fallback."""
from __future__ import annotations

from typing import Any, Mapping

from aether.contracts import RuntimeCommand, RuntimeResult
from aether.contracts.event_types import EventType
from aether.events import EventBus

from .registry import RuntimeAdapterRegistry


class CodingRuntimeDispatchAdapter:
    OPERATION = "coding.task.execute"

    def __init__(self, registry: RuntimeAdapterRegistry, *, event_bus: EventBus | None = None,
                 routing_key: str = "runtime://coding/dispatch", maximum_attempts: int = 2) -> None:
        self.registry = registry
        self.event_bus = event_bus
        self.routing_key = routing_key
        self.maximum_attempts = max(1, maximum_attempts)

    @property
    def adapter_id(self) -> str:
        return "runtime.coding.dispatch"

    async def capabilities(self) -> set[str]:
        return {self.OPERATION}

    async def health(self) -> Mapping[str, Any]:
        descriptors = await self.registry.discover()
        healthy = [item for item in descriptors if item.health_status.value == "healthy"]
        return {"ok": bool(healthy), "adapter_id": self.adapter_id, "healthy_runtime_count": len(healthy)}

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        if command.command != self.OPERATION:
            return RuntimeResult(False, error=f"Unsupported dispatch command: {command.command}", metadata={"error_type": "CommandDenied"})
        candidates = [dict(item) for item in command.arguments.get("runtime_candidates") or ()]
        if not candidates:
            return RuntimeResult(False, error="No runtime candidates were bound to the approved action", metadata={"error_type": "NoRuntimeCandidates"})
        attempts: list[dict[str, Any]] = []
        last: RuntimeResult | None = None
        for index, candidate in enumerate(candidates[: self.maximum_attempts], start=1):
            routing_key = str(candidate.get("routing_key") or "")
            adapter_id = str(candidate.get("adapter_id") or routing_key)
            try:
                adapter = self.registry.adapter(routing_key)
                result = await adapter.execute(RuntimeCommand(
                    command=self.OPERATION,
                    arguments={
                        "task": command.arguments.get("task"),
                        "workspace_binding": command.arguments.get("workspace_binding"),
                        "runtime_descriptor": candidate,
                    },
                    capability=command.capability,
                    correlation_id=command.correlation_id,
                    timeout_seconds=command.timeout_seconds,
                ))
            except Exception as exc:
                result = RuntimeResult(False, error=f"{type(exc).__name__}: {exc}", metadata={"error_type": type(exc).__name__})
            last = result
            attempts.append({
                "attempt": index,
                "routing_key": routing_key,
                "runtime_adapter_id": adapter_id,
                "ok": result.ok,
                "error": result.error,
                "failure_fingerprint": result.metadata.get("failure_fingerprint"),
            })
            if result.ok:
                if index > 1:
                    self._emit(EventType.CODING_TASK_PROGRESS, {
                        "task_id": str((command.arguments.get("task") or {}).get("task_id") or ""),
                        "phase": "fallback",
                        "message": f"Fallback runtime succeeded: {adapter_id}",
                        "sequence": 900,
                        "metadata": {"attempt": index},
                    }, correlation_id=command.correlation_id)
                return RuntimeResult(True, result.output, metadata={
                    **dict(result.metadata),
                    "dispatch_adapter_id": self.adapter_id,
                    "selected_runtime_adapter_id": adapter_id,
                    "selected_runtime_routing_key": routing_key,
                    "runtime_attempts": attempts,
                    "fallback_used": index > 1,
                })
        error = last.error if last is not None else "All coding runtime candidates failed"
        return RuntimeResult(False, error=error, metadata={
            **(dict(last.metadata) if last is not None else {}),
            "dispatch_adapter_id": self.adapter_id,
            "selected_runtime_adapter_id": attempts[-1]["runtime_adapter_id"] if attempts else None,
            "runtime_attempts": attempts,
            "fallback_used": len(attempts) > 1,
        })

    def _emit(self, event_type: EventType, payload: Mapping[str, Any], *, correlation_id: str | None = None) -> None:
        if self.event_bus is not None:
            self.event_bus.emit(event_type, actor=self.adapter_id, payload=dict(payload), correlation_id=correlation_id)
