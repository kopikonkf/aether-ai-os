from typing import Optional

from aether_tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self, behavior_monitor: Optional['BehaviorMonitor'] = None):
        self._tools: dict[str, Tool] = {}
        self.behavior_monitor = behavior_monitor

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def manifest(self) -> str:
        return "\n".join(f"[TOOL {tool.name} {tool.spec}]" for tool in self._tools.values())

    def validate(self, name: str, **kwargs) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(False, "", None, f"Unknown tool: {name}")
        try:
            return tool.validate(**kwargs)
        except Exception as exc:
            return ToolResult(False, "", None, f"Tool preflight failed: {exc}")

    def execute(self, name: str, **kwargs) -> ToolResult:
        tool = self.get(name)
        if not tool:
            result = ToolResult(False, "", None, f"Unknown tool: {name}")
            if self.behavior_monitor:
                self.behavior_monitor.record_error()
            return result

        if self.behavior_monitor:
            self.behavior_monitor.record_tool_call()
            if name in ("write", "edit"):
                self.behavior_monitor.record_file_write()

        try:
            result = tool(**kwargs)
            if self.behavior_monitor and not result.ok:
                self.behavior_monitor.record_error()
            return result
        except Exception as exc:
            if self.behavior_monitor:
                self.behavior_monitor.record_error()
            return ToolResult(False, "", None, f"Tool execution failed: {exc}")
