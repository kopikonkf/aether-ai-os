"""Adapter from Aether's provider-neutral ToolExecutor port to aether-tools."""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from aether.contracts.actions import ActionCapability, ActionScope, ActionTarget
from aether.contracts.runtime import RuntimeResult
from aether_tools import ToolRegistry


_TOOL_POLICIES: dict[str, tuple[tuple[ActionScope, ...], bool, str, dict[str, Any]]] = {
    "read": (
        (ActionScope.READ,), True, "Read a text file inside configured roots",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
    ),
    "glob": (
        (ActionScope.READ,), True, "List files matching a pattern inside configured roots",
        {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"], "additionalProperties": False},
    ),
    "grep": (
        (ActionScope.READ,), True, "Search text inside configured roots",
        {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"], "additionalProperties": False},
    ),
    "write": (
        (ActionScope.WRITE,), False, "Write or overwrite a UTF-8 text file inside configured roots",
        {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False},
    ),
    "edit": (
        (ActionScope.WRITE,), False, "Replace the first exact text match inside a file in configured roots",
        {"type": "object", "properties": {"path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}}, "required": ["path", "find", "replace"], "additionalProperties": False},
    ),
    "bash": (
        (ActionScope.EXECUTE,), False, "Run a policy-restricted platform shell command in Aether's bounded workspace",
        {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout": {"type": "integer", "minimum": 1, "maximum": 60}}, "required": ["cmd"], "additionalProperties": False},
    ),
    "webfetch": (
        (ActionScope.NETWORK,), True, "Fetch a bounded public HTTPS resource",
        {"type": "object", "properties": {"url": {"type": "string"}, "format": {"type": "string", "enum": ["markdown", "text", "html"]}}, "required": ["url"], "additionalProperties": False},
    ),
    "memory": (
        (ActionScope.MEMORY,), False, "Access operational key/value memory",
        {"type": "object", "properties": {"op": {"type": "string", "enum": ["store", "recall", "search"]}, "key": {"type": "string"}, "value": {"type": "string"}, "query": {"type": "string"}}, "required": ["op"], "additionalProperties": False},
    ),
}


class RegistryToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def capabilities(self) -> Sequence[ActionCapability]:
        result: list[ActionCapability] = []
        for tool in self.registry.all():
            scopes, reversible, description, schema = _TOOL_POLICIES.get(
                tool.name,
                ((ActionScope.EXECUTE,), False, f"Execute registered tool {tool.name}", {"type": "object"}),
            )
            result.append(ActionCapability(
                target=ActionTarget.TOOL,
                operation=tool.name,
                description=description,
                required_scopes=scopes,
                reversible=reversible,
                input_schema=schema,
            ))
        return result

    async def validate_tool(self, operation: str, arguments: Mapping[str, Any]) -> RuntimeResult:
        result = await asyncio.to_thread(self.registry.validate, operation, **dict(arguments))
        return RuntimeResult(
            ok=result.ok,
            output=result.output if result.ok else None,
            error=result.error,
            metadata={"backend": "tool-registry", "tool": operation, "preflight": True, "data": result.data or {}},
        )

    async def execute_tool(self, operation: str, arguments: Mapping[str, Any]) -> RuntimeResult:
        result = await asyncio.to_thread(self.registry.execute, operation, **dict(arguments))
        return RuntimeResult(
            ok=result.ok,
            output=result.output if result.ok else None,
            error=result.error,
            metadata={"backend": "tool-registry", "tool": operation, "data": result.data or {}},
        )
