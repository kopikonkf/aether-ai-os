"""Production-facing Aether Living Machine MCP surface.

The existing Aether Operational MCP remains unchanged. This server composes a
new capability plane over the already-instantiated Gateway runtime, workspace
binding store, telemetry store, and GovernedActionPath.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import sys
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.responses import JSONResponse

from . import living_machine
from .living_machine import LivingMachineMCPService, LivingMachinePolicyError

# Importing the composition root is intentional: this surface is an interface
# over the running Gateway objects, not a second runtime implementation.
from aether_gateway.api import server as gateway


_auth_role: contextvars.ContextVar[str] = contextvars.ContextVar("aether_mcp_auth_role", default="none")


def auth_role() -> str:
    return _auth_role.get()


class MCPAuthMiddleware:
    """Dedicated bearer credentials at the MCP ingress boundary.

    READ token -> read/diagnostic. Operator token -> read/diagnostic/mutate.
    Health is deliberately unauthenticated for process probes; it contains no
    private state.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.read_token = os.getenv("AETHER_MCP_TOKEN", "").strip()
        self.operator_token = os.getenv("AETHER_MCP_OPERATOR_TOKEN", "").strip()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        if path == "/health":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        supplied = headers.get("authorization", "")
        token = supplied[7:].strip() if supplied.lower().startswith("bearer ") else ""
        role = "none"
        if self.operator_token and token and __import__("hmac").compare_digest(token, self.operator_token):
            role = "operator"
        elif self.read_token and token and __import__("hmac").compare_digest(token, self.read_token):
            role = "read"
        if role == "none":
            body = b'{"error":"authentication_required"}'
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        token_state = _auth_role.set(role)
        try:
            await self.app(scope, receive, send)
        finally:
            _auth_role.reset(token_state)


service = LivingMachineMCPService(
    project_root=gateway.PROJECT_ROOT,
    aether_home=gateway.root_dir,
    workspace_roots=gateway.coding_allowed_roots,
    workspace_bindings=gateway.workspace_bindings,
    runtime_registry=gateway.runtime_registry,
    runtime_telemetry=gateway.runtime_telemetry,
    action_path=gateway.action_path,
    coding_runtime_key=gateway.coding_dispatch_adapter.routing_key,
)

_transport_security = None
try:
    from mcp.server.transport_security import TransportSecuritySettings as _TransportSecurity
    _allowed_hosts = ["127.0.0.1", "localhost", "localhost:*", "127.0.0.1:*"]
    _allowed_origins: list[str] = []
    _public_host = os.getenv("AETHER_MCP_PUBLIC_HOSTNAME", "").strip()
    if _public_host:
        _allowed_hosts.extend([_public_host, f"{_public_host}:*"])
        _allowed_origins.append(f"https://{_public_host}")
    # Hardcode production public hostname — not a secret, just the routing hostname.
    # Cloudflare Tunnel + Caddy + Bearer auth provide the actual security boundary.
    for _h in ["aethers.my.id", "aethers.my.id:443"]:
        if _h not in _allowed_hosts:
            _allowed_hosts.append(_h)
    _allowed_origins.append("https://aethers.my.id")
    _transport_security = _TransportSecurity(allowed_hosts=_allowed_hosts, allowed_origins=_allowed_origins)
except Exception:
    _transport_security = None

mcp = FastMCP(
    "Aether Living Machine MCP",
    instructions=(
        "Controlled access to the live Aether machine. READ/DIAGNOSTIC are bounded; "
        "verification is allowlisted; mutation is submitted by an operator credential "
        "but execution REQUIRES a trusted human decision through the Trusted Approval "
        "Inbox (pending-approval is returned, never self-approving). Mutation routes "
        "through GovernedActionPath and the existing LocalStructuredCodingRuntimeAdapter. "
        "Never assume shell, secret access, or governance authority."
    ),
    host="127.0.0.1",
    port=int(os.getenv("AETHER_MCP_PORT", "8787")),
    stateless_http=True,
    json_response=True,
    transport_security=_transport_security,
)


@mcp.resource("aether://runtime/status")
async def runtime_status_resource() -> str:
    return json.dumps(await service.runtime_status(), ensure_ascii=False, indent=2)


@mcp.resource("aether://runtime/adapters")
async def runtime_adapters_resource() -> str:
    return json.dumps(await service.runtime_adapters(), ensure_ascii=False, indent=2)


@mcp.resource("aether://runtime/telemetry")
def runtime_telemetry_resource() -> str:
    return json.dumps(service.runtime_telemetry(), ensure_ascii=False, indent=2)


@mcp.resource("aether://workspace/{workspace_id}/manifest")
def workspace_manifest_resource(workspace_id: str) -> str:
    return json.dumps(service.workspace_manifest(workspace_id), ensure_ascii=False, indent=2)


@mcp.tool()
def aether_living_capabilities() -> dict[str, Any]:
    """Return the live-machine capability manifest and security boundary."""
    return service.capability_manifest()


@mcp.tool()
def workspace_list(limit: int = 100) -> dict[str, Any]:
    """List immutable Aether workspace bindings without exposing session secrets."""
    return service.workspace_list(limit)


@mcp.tool()
def workspace_tree(path: str = ".", depth: int = 3, limit: int = 200) -> dict[str, Any]:
    """List a bounded tree inside an allowed Aether root."""
    return service.workspace_tree(path, depth, limit)


@mcp.tool()
def file_read(path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
    """Read bounded text from an allowed non-secret file."""
    return service.file_read(path, start_line, end_line)


@mcp.tool()
def file_search(query: str, root: str = ".", limit: int = 50) -> dict[str, Any]:
    """Search text and filenames inside an allowed root."""
    return service.file_search(query, root, limit)


@mcp.tool()
def file_glob(pattern: str, root: str = ".", limit: int = 100) -> dict[str, Any]:
    """Find files by a bounded glob inside an allowed root."""
    return service.file_glob(pattern, root, limit)


@mcp.tool()
def file_hash(path: str) -> dict[str, Any]:
    """Return SHA-256 evidence for an allowed file."""
    return service.file_hash(path)


@mcp.tool()
async def runtime_status() -> dict[str, Any]:
    """Return live runtime adapter and telemetry status."""
    return await service.runtime_status()


@mcp.tool()
async def runtime_health() -> dict[str, Any]:
    """Discover and health-check registered runtime adapters."""
    return await service.runtime_health()


@mcp.tool()
async def runtime_adapters() -> dict[str, Any]:
    """Return runtime descriptors and health projections."""
    return await service.runtime_adapters()


@mcp.tool()
def runtime_telemetry(limit: int = 50) -> dict[str, Any]:
    """Return bounded runtime invocation telemetry."""
    return service.runtime_telemetry(limit)


@mcp.tool()
def service_status() -> dict[str, Any]:
    """Probe the local Aether Gateway health endpoint without returning secrets."""
    return service.service_status()


@mcp.tool()
def logs_tail(component: str, lines: int = 200, since: str | None = None) -> dict[str, Any]:
    """Return bounded, redacted logs for a named component."""
    return service.logs_tail(component, lines, since)


@mcp.tool()
async def run_verification(workspace_id: str, session_id: str, verification_id: str) -> dict[str, Any]:
    """Run one explicitly registered, non-shell verification command."""
    return await service.run_verification(workspace_id, session_id, verification_id)


@mcp.tool()
def get_verification_receipt(invocation_id: str) -> dict[str, Any]:
    """Retrieve a bounded verification/runtime receipt."""
    return service.get_verification_receipt(invocation_id)


@mcp.tool()
def get_runtime_task(task_id: str) -> dict[str, Any]:
    """Retrieve a bounded runtime task receipt."""
    return service.get_runtime_task(task_id)


@mcp.tool()
def git_status() -> dict[str, Any]:
    """Read-only Git status for the versioned Aether repository."""
    return service.git_status()


@mcp.tool()
def git_diff(staged: bool = False, path: str | None = None) -> dict[str, Any]:
    """Read-only Git diff; no Git mutation is exposed."""
    return service.git_diff(staged, path)


@mcp.tool()
def git_log(limit: int = 20) -> dict[str, Any]:
    """Read-only recent Git history."""
    return service.git_log(limit)


def _require_operator() -> None:
    if auth_role() != "operator":
        raise LivingMachinePolicyError("mutation requires the dedicated MCP operator credential")


@mcp.tool()
async def workspace_edit(workspace_id: str, session_id: str, edits: list[dict[str, Any]], verification_commands: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """Apply structured edits through GovernedActionPath and the existing coding runtime."""
    _require_operator()
    return await service.workspace_edit(workspace_id=workspace_id, session_id=session_id, edits=edits, verification_commands=verification_commands, reason=reason, operator=os.getenv("AETHER_MCP_OPERATOR_ID", "mcp-operator"), operator_token=os.getenv("AETHER_MCP_OPERATOR_TOKEN"))


@mcp.tool()
async def workspace_apply_patch(workspace_id: str, session_id: str, edits: list[dict[str, Any]], verification_commands: list[dict[str, Any]], reason: str) -> dict[str, Any]:
    """Alias for governed structured workspace mutation; no raw write API exists."""
    return await workspace_edit(workspace_id, session_id, edits, verification_commands, reason)


@mcp.tool()
async def workspace_rollback(task_id: str, workspace_id: str, session_id: str, reason: str) -> dict[str, Any]:
    """Return the authoritative automatic rollback receipt for a failed coding task."""
    _require_operator()
    return await service.workspace_rollback(task_id, workspace_id, session_id, reason, os.getenv("AETHER_MCP_OPERATOR_ID", "mcp-operator"), os.getenv("AETHER_MCP_OPERATOR_TOKEN"))


@contextlib.asynccontextmanager
async def _lifespan(_: Starlette):
    async with contextlib.AsyncExitStack():
        yield


def build_http_app() -> Starlette:
    # The SDK's Streamable HTTP app owns the MCP protocol route/lifespan. The
    # outer Starlette app adds only authentication and the process health probe.
    mcp_app = mcp.streamable_http_app()

    async def health(scope: dict[str, Any], receive: Any, send: Any) -> None:
        body = json.dumps({"status": "ok", "service": "aether-living-machine-mcp", "authenticated_transport": bool(os.getenv("AETHER_MCP_TOKEN") or os.getenv("AETHER_MCP_OPERATOR_TOKEN"))}).encode()
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    class HealthRoute:
        async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
            await health(scope, receive, send)

    from starlette.routing import Route
    return Starlette(routes=[Route("/health", HealthRoute(), methods=["GET"]), Mount("/", app=MCPAuthMiddleware(mcp_app))], lifespan=_lifespan)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Aether Living Machine MCP")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--host", default=os.getenv("AETHER_MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("AETHER_MCP_PORT", "8787")))
    args = parser.parse_args(argv)
    if args.transport == "stdio":
        if os.getenv("AETHER_MCP_STDIO_OPERATOR", "false").casefold() in {"1", "true", "yes"}:
            _auth_role.set("operator")
        mcp.run(transport="stdio")
    else:
        if args.host not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("Aether MCP must bind to loopback; use Cloudflare/Caddy for remote ingress")
        uvicorn.run(build_http_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
