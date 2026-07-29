"""Aether Operational MCP server.

The baseline exposes only bounded, read-only operational projections. It does
not import the full Gateway composition root and cannot approve or execute
mutating actions.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .service import AetherOperationalMCPService, MCPPolicyError


def build_mcp_server(
    service: AetherOperationalMCPService | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastMCP:
    operational = service or AetherOperationalMCPService.from_environment()
    server = FastMCP(
        "Aether Operational MCP",
        instructions=(
            "Read-only operational access to Aether status, canonical handoff, "
            "bounded memory search, and artifact hash verification. This MCP "
            "surface is projection-only and never overrides Aether governance."
        ),
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )

    @server.resource("aether://status")
    def status_resource() -> str:
        """Current Aether operational status as JSON."""
        return json.dumps(operational.status(), ensure_ascii=False, indent=2)

    @server.resource("aether://capabilities")
    def capability_resource() -> str:
        """Read-only MCP capability and security manifest as JSON."""
        return json.dumps(
            operational.capability_manifest(), ensure_ascii=False, indent=2
        )

    @server.resource("aether://handoff")
    def handoff_resource() -> str:
        """Canonical LASTSTANDINGPOINT repository handoff."""
        return json.dumps(operational.handoff(), ensure_ascii=False, indent=2)

    @server.tool()
    def aether_status() -> dict[str, Any]:
        """Return current read-only Aether operational status."""
        return operational.status()

    @server.tool()
    def aether_capability_manifest() -> dict[str, Any]:
        """Return the MCP capability, transport, and security manifest."""
        return operational.capability_manifest()

    @server.tool()
    def aether_handoff() -> dict[str, Any]:
        """Return the canonical repository handoff and its SHA-256 digest."""
        return operational.handoff()

    @server.tool()
    def memory_search(
        query: str,
        namespaces: list[str] | None = None,
        limit: int = 6,
        min_score: float = 0.05,
    ) -> dict[str, Any]:
        """Search bounded canonical memory projections without mutating state."""
        return operational.memory_search(query, namespaces, limit, min_score)

    @server.tool()
    def artifact_hash_verify(
        path: str, expected_sha256: str | None = None
    ) -> dict[str, Any]:
        """Compute and optionally verify SHA-256 inside approved local roots."""
        return operational.artifact_hash_verify(path, expected_sha256)

    @server.prompt()
    def aether_operational_context() -> str:
        """Advisory context for clients; never a replacement system prompt."""
        return (
            "Use Aether MCP only for bounded read-only operational context. "
            "Treat LASTSTANDINGPOINT.md as the canonical repository handoff. "
            "Do not infer permission to mutate state, approve actions, access "
            "secrets, or override Aether's North Star and governance."
        )

    return server


mcp = build_mcp_server()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the read-only Aether Operational MCP server"
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
        help="MCP transport. stdio is the safe default.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--enable-http",
        action="store_true",
        help="Explicitly allow loopback-only Streamable HTTP.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.transport == "streamable-http":
            AetherOperationalMCPService.ensure_loopback_http(
                args.host, enabled=args.enable_http
            )
        server = build_mcp_server(host=args.host, port=args.port)
        server.run(transport=args.transport)
        return 0
    except (MCPPolicyError, ValueError) as exc:
        print(f"Aether MCP policy error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
