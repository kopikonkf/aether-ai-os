"""Minimal SDK primitives and conformance checks for coding runtime adapters."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from aether.contracts import RuntimeCommand, RuntimeResult
from aether.contracts.coding_runtime import RuntimeDescriptor


class RuntimeAdapterConformanceError(ValueError):
    pass


class CodingRuntimeAdapterBase(ABC):
    """Base class for replaceable coding bodies.

    Adapters own transport and execution mechanics only. They do not own Aether
    identity, workspace authority, governance, or canonical skill state.
    """

    @property
    @abstractmethod
    def adapter_id(self) -> str: ...

    @property
    @abstractmethod
    def descriptor(self) -> RuntimeDescriptor: ...

    async def capabilities(self) -> set[str]:
        return set(self.descriptor.operations)

    @abstractmethod
    async def health(self) -> Mapping[str, Any]: ...

    async def discover_descriptor(self) -> RuntimeDescriptor:
        """Optional live discovery hook used by external runtimes."""
        return self.descriptor

    @abstractmethod
    async def execute(self, command: RuntimeCommand) -> RuntimeResult: ...


def validate_runtime_adapter(adapter, descriptor: RuntimeDescriptor) -> None:
    errors: list[str] = []
    adapter_id = str(getattr(adapter, "adapter_id", "") or "")
    if not adapter_id:
        errors.append("adapter_id is required")
    if adapter_id != descriptor.adapter_id:
        errors.append("descriptor adapter_id does not match adapter")
    if not descriptor.routing_key.strip():
        errors.append("routing_key is required")
    if not descriptor.operations:
        errors.append("at least one private runtime operation is required")
    if "coding.task.execute" not in descriptor.operations:
        errors.append("coding runtime must implement coding.task.execute")
    if not descriptor.capabilities:
        errors.append("at least one coding capability is required")
    for method in ("capabilities", "health", "execute"):
        if not callable(getattr(adapter, method, None)):
            errors.append(f"adapter method is missing: {method}")
    if errors:
        raise RuntimeAdapterConformanceError("; ".join(errors))
