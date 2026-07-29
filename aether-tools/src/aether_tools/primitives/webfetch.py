from urllib.parse import urlparse

import requests

from aether_tools.base import Tool, ToolResult


class WebFetchTool(Tool):
    name = "webfetch"
    spec = 'url="https://..." format="markdown|text|html"'

    def __init__(self, max_bytes: int = 1048576, https_only: bool = True):
        self.max_bytes = max_bytes
        self.https_only = https_only

    def validate(self, url: str = "", format: str = "markdown", **kwargs) -> ToolResult:
        if not url:
            return ToolResult(False, "", None, "url required")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ToolResult(False, "", None, "url must be an absolute HTTP(S) URL")
        if self.https_only and parsed.scheme != "https":
            return ToolResult(False, "", None, "Only HTTPS URLs are allowed by policy")
        if format not in {"markdown", "text", "html"}:
            return ToolResult(False, "", None, "format must be markdown, text, or html")
        return ToolResult(True, "Web fetch preflight passed.", {"url": url, "format": format})

    def __call__(self, url: str = "", format: str = "markdown", **kwargs) -> ToolResult:
        preflight = self.validate(url=url, format=format)
        if not preflight.ok:
            return preflight
        try:
            response = requests.get(url, timeout=30, headers={"User-Agent": "Aether/0.19.2"})
            response.raise_for_status()
            raw = response.content[:self.max_bytes]
            content = raw.decode(response.encoding or "utf-8", errors="replace")
            if format == "text":
                import html
                content = html.unescape(content)
            return ToolResult(True, content, {"status": response.status_code, "size": len(raw), "url": url})
        except Exception as exc:
            return ToolResult(False, "", None, str(exc))
