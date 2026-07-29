from __future__ import annotations

from typing import Any, Mapping

from aether.contracts.runtime import RuntimeAdapter, RuntimeCommand, RuntimeResult


class RuntimeHostAdapter(RuntimeAdapter):
    """Safe no-op reference adapter used to validate the runtime boundary."""

    @property
    def adapter_id(self) -> str:
        return "runtime-host"

    async def capabilities(self) -> set[str]:
        return {"text", "tool_use"}

    async def health(self) -> Mapping[str, Any]:
        return {"ok": True, "adapter_id": self.adapter_id, "mode": "reference"}

    async def execute(self, command: RuntimeCommand) -> RuntimeResult:
        return RuntimeResult(
            ok=True,
            output={"command": command.command, "arguments": dict(command.arguments)},
            metadata={"adapter_id": self.adapter_id, "reference_adapter": True},
        )
