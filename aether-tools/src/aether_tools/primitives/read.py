from pathlib import Path

from aether_tools.base import Tool, ToolResult
from aether_tools.primitives.scope import allowed_roots_text, resolve_path


class ReadTool(Tool):
    name = "read"
    spec = 'path="relative/or/absolute/path"'

    def __init__(self, read_roots: list[Path], max_lines: int = 500, max_size: int = 524288):
        self.read_roots = read_roots
        self.max_lines = max_lines
        self.max_size = max_size

    def validate(self, path: str = "", **kwargs) -> ToolResult:
        if not str(path or "").strip():
            return ToolResult(False, "", None, "path required")
        full = resolve_path(path, self.read_roots)
        if not full:
            roots = allowed_roots_text(self.read_roots)
            return ToolResult(False, "", {"allowed_roots": roots}, f"Read access denied; target is outside configured roots: {path}. Allowed roots: {roots}.")
        if not full.is_file():
            return ToolResult(False, "", {"path": str(full)}, f"File not found: {full}")
        try:
            size = full.stat().st_size
        except OSError as exc:
            return ToolResult(False, "", {"path": str(full)}, str(exc))
        if size > self.max_size:
            return ToolResult(False, "", {"path": str(full), "size": size}, f"File exceeds maximum readable size of {self.max_size} bytes: {full}")
        return ToolResult(True, "Read preflight passed.", {"path": str(full), "size": size})

    def __call__(self, path: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(path=path)
        if not preflight.ok:
            return preflight
        full = Path(str((preflight.data or {})["path"]))
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            if len(lines) > self.max_lines:
                text = "".join(lines[:self.max_lines]) + f"\n... [truncated at {self.max_lines} lines]"
            return ToolResult(True, text, {"path": str(full), "lines": text.count("\n") + 1})
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
