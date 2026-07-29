from pathlib import Path
import hashlib

from aether_tools.base import Tool, ToolResult
from aether_tools.primitives.scope import allowed_roots_text, resolve_write_path


class WriteTool(Tool):
    name = "write"
    spec = 'path="relative/path" content="text"'

    def __init__(self, write_roots: list[Path]):
        self.write_roots = write_roots

    @staticmethod
    def _content(_body: str = "", content: str = "") -> str:
        # `_body` preserves the legacy tag parser; `content` is the canonical
        # native function-call argument exposed to modern model providers.
        return _body if _body else content

    def validate(self, path: str = "", _body: str = "", content: str = "", **kwargs) -> ToolResult:
        if not str(path or "").strip():
            return ToolResult(False, "", None, "path required")
        body = self._content(_body, content)
        if not body:
            return ToolResult(False, "", None, "content required")
        full = resolve_write_path(path, self.write_roots)
        if not full:
            roots = allowed_roots_text(self.write_roots)
            return ToolResult(
                False,
                "",
                {"allowed_roots": roots, "requested_path": path},
                f"Write access denied; target is outside configured roots: {path}. Allowed roots: {roots}. "
                "Use a relative path such as workspace/first-experience.md, or explicitly add a trusted root to tool_policy.yaml and restart Gateway.",
            )
        return ToolResult(True, "Write preflight passed.", {"path": str(full)})

    def __call__(self, path: str = "", _body: str = "", content: str = "", **kwargs) -> ToolResult:
        preflight = self.validate(path=path, _body=_body, content=content)
        if not preflight.ok:
            return preflight
        full = Path(str((preflight.data or {})["path"]))
        try:
            existed = full.exists()
            full.parent.mkdir(parents=True, exist_ok=True)
            body = self._content(_body, content).lstrip("\n")
            encoded = body.encode("utf-8")
            full.write_bytes(encoded)
            size = len(encoded)
            digest = hashlib.sha256(encoded).hexdigest()
            return ToolResult(
                True,
                f"Wrote {size} bytes to {full}",
                {
                    "path": str(full),
                    "size": size,
                    "sha256": digest,
                    "disposition": "overwritten" if existed else "created",
                },
            )
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
