"""Governed Model Context Protocol surfaces for Aether."""

from .service import AetherOperationalMCPService, MCPPolicyError, ReadOnlyMemoryProjection

__all__ = [
    "AetherOperationalMCPService",
    "MCPPolicyError",
    "ReadOnlyMemoryProjection",
    "build_mcp_server",
    "mcp",
]


def __getattr__(name: str):
    if name in {"build_mcp_server", "mcp"}:
        from .server import build_mcp_server, mcp

        return {"build_mcp_server": build_mcp_server, "mcp": mcp}[name]
    raise AttributeError(name)
