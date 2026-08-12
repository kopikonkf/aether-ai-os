"""Bootstrap composition for the Living Machine MCP server."""
from __future__ import annotations

from . import living_server
from .governed_coding import GovernedMCPActionPath
from aether_gateway.api import server as gateway

living_server.service.action_path = GovernedMCPActionPath(
    gateway.action_path,
    gateway.runtime_registry,
    gateway.coding_dispatch_adapter.routing_key,
)

mcp = living_server.mcp
MCPAuthMiddleware = living_server.MCPAuthMiddleware
