from pathlib import Path

from aether_tools.base import Tool, ToolResult
from aether_tools.primitives.scope import allowed_roots_text, resolve_path


class GlobTool(Tool):
    name = "glob"
    spec = 'pattern="**/*.py" path="root/dir"'

    def __init__(self, read_roots: list[Path]):
        self.read_roots = read_roots

    def validate(self, pattern: str = "", path: str = "", **kwargs) -> ToolResult:
        if not pattern:
            return ToolResult(False, "", None, "pattern required")
        search_root = resolve_path(path, self.read_roots) if path else Path(self.read_roots[0]).resolve()
        if not search_root:
            roots = allowed_roots_text(self.read_roots)
            return ToolResult(False, "", {"allowed_roots": roots}, f"Glob path is outside configured roots: {path}. Allowed roots: {roots}.")
        if not search_root.is_dir():
            return ToolResult(False, "", {"path": str(search_root)}, f"Directory not found: {search_root}")
        return ToolResult(True, "Glob preflight passed.", {"path": str(search_root)})

    def __call__(self, pattern: str = "", path: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(pattern=pattern, path=path)
        if not preflight.ok:
            return preflight
        search_root = Path(str((preflight.data or {})["path"]))
        try:
            matches = [str(item.relative_to(search_root)) for item in sorted(search_root.rglob(pattern)) if item.is_file()]
            output = "\n".join(matches[:200]) if matches else "No matches."
            if len(matches) > 200:
                output += f"\n... ({len(matches) - 200} more matches)"
            return ToolResult(True, output, {"matches": len(matches), "path": str(search_root)})
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
