from pathlib import Path

from aether_tools.base import Tool, ToolResult
from aether_tools.primitives.scope import allowed_roots_text, resolve_write_path


class EditTool(Tool):
    name = "edit"
    spec = 'path="file" find="text" replace="new text"'

    def __init__(self, write_roots: list[Path]):
        self.write_roots = write_roots

    def validate(self, path: str = "", find: str = "", replace: str = "", **kwargs) -> ToolResult:
        if not str(path or "").strip() or not find:
            return ToolResult(False, "", None, "path and find required")
        full = resolve_write_path(path, self.write_roots)
        if not full:
            roots = allowed_roots_text(self.write_roots)
            return ToolResult(False, "", {"allowed_roots": roots}, f"Edit access denied; target is outside configured roots: {path}. Allowed roots: {roots}.")
        if not full.is_file():
            return ToolResult(False, "", {"path": str(full)}, f"File not found: {full}")
        try:
            text = full.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(False, "", {"path": str(full)}, str(exc))
        if find not in text:
            return ToolResult(False, "", {"path": str(full)}, f"Pattern not found in {full}")
        return ToolResult(True, "Edit preflight passed.", {"path": str(full)})

    def __call__(self, path: str = "", find: str = "", replace: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(path=path, find=find, replace=replace)
        if not preflight.ok:
            return preflight
        full = Path(str((preflight.data or {})["path"]))
        try:
            text = full.read_text(encoding="utf-8")
            full.write_text(text.replace(find, replace, 1), encoding="utf-8")
            return ToolResult(True, f"Replaced text in {full}", {"path": str(full)})
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
