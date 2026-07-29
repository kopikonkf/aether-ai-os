import re
from pathlib import Path

from aether_tools.base import Tool, ToolResult
from aether_tools.primitives.scope import allowed_roots_text, resolve_path


class GrepTool(Tool):
    name = "grep"
    spec = 'pattern="regex" path="root/dir"'

    def __init__(self, read_roots: list[Path]):
        self.read_roots = read_roots

    def validate(self, pattern: str = "", path: str = "", **kwargs) -> ToolResult:
        if not pattern:
            return ToolResult(False, "", None, "pattern required")
        try:
            re.compile(pattern)
        except re.error as exc:
            return ToolResult(False, "", None, f"Regex error: {exc}")
        search_root = resolve_path(path, self.read_roots) if path else Path(self.read_roots[0]).resolve()
        if not search_root:
            roots = allowed_roots_text(self.read_roots)
            return ToolResult(False, "", {"allowed_roots": roots}, f"Search path is outside configured roots: {path}. Allowed roots: {roots}.")
        if not search_root.is_dir():
            return ToolResult(False, "", {"path": str(search_root)}, f"Directory not found: {search_root}")
        return ToolResult(True, "Grep preflight passed.", {"path": str(search_root)})

    def __call__(self, pattern: str = "", path: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(pattern=pattern, path=path)
        if not preflight.ok:
            return preflight
        search_root = Path(str((preflight.data or {})["path"]))
        try:
            compiled = re.compile(pattern)
            results = []
            for file_path in search_root.rglob("*"):
                if file_path.is_file() and file_path.suffix in {
                    ".py", ".md", ".txt", ".yaml", ".yml", ".json", ".toml",
                    ".cfg", ".ini", ".env", ".bat", ".sh", ".ps1",
                    ".html", ".css", ".js", ".ts", ".jsx", ".tsx",
                    ".xml", ".csv", ".log",
                }:
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="replace")
                        for line_number, line in enumerate(text.splitlines(), 1):
                            if compiled.search(line):
                                rel = file_path.relative_to(search_root)
                                results.append(f"{rel}:{line_number}: {line.strip()[:200]}")
                    except Exception:
                        continue
            output = "\n".join(results[:100]) if results else "No matches found."
            if len(results) > 100:
                output += f"\n... ({len(results) - 100} more matches)"
            return ToolResult(True, output, {"matches": len(results), "path": str(search_root)})
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
