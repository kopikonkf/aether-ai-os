"""Runnable entrypoint for Aether Living Machine MCP."""
from __future__ import annotations

import argparse
import contextlib
import os

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .living_server_bootstrap import MCPAuthMiddleware, mcp


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    async with mcp.session_manager.run():
        yield


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "aether-living-machine-mcp", "authentication_configured": bool(os.getenv("AETHER_MCP_TOKEN", "").strip() or os.getenv("AETHER_MCP_OPERATOR_TOKEN", "").strip())})


def build_http_app() -> Starlette:
    return Starlette(routes=[Route("/health", health, methods=["GET"]), Mount("/", app=MCPAuthMiddleware(mcp.streamable_http_app()))], lifespan=lifespan)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aether Living Machine MCP")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default=os.getenv("AETHER_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AETHER_MCP_PORT", "8787")))
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("Aether MCP must bind to loopback; use Cloudflare/Caddy for remote ingress")
        uvicorn.run(build_http_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
