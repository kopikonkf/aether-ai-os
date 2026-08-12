# Aether Living Machine MCP — Deployment

## Process

The new server is exposed as:

```text
aether-living-mcp --transport stdio
aether-living-mcp --transport streamable-http --host 127.0.0.1 --port 8787
```

The process must bind to loopback. Remote access goes through the existing Cloudflare Tunnel/Caddy ingress; do not expose 8787 directly.

## Credentials

Set dedicated secrets outside source control:

```text
AETHER_MCP_TOKEN=<read-diagnostic bearer token>
AETHER_MCP_OPERATOR_TOKEN=<separate mutation/operator bearer token>
AETHER_MCP_OPERATOR_ID=<operator identity>
```

Optional bounds/configuration:

```text
AETHER_MCP_PORT=8787
AETHER_MCP_MAX_FILE_BYTES=262144
AETHER_MCP_MAX_RESULTS=100
AETHER_MCP_MAX_LOG_BYTES=262144
AETHER_MCP_MAX_LOG_LINES=500
AETHER_MCP_LOG_ROOTS=<os-path-list>
AETHER_MCP_GATEWAY_HEALTH_URL=http://127.0.0.1:8000/health
AETHER_MCP_VERIFICATIONS=<JSON registry of named argv arrays>
```

Never put these credentials into Git, command-line arguments, MCP tool arguments, or telemetry.

## Cloudflare

Add a private ingress route from the existing Cloudflare tunnel to:

```text
http://127.0.0.1:8787
```

The public hostname must be protected by the existing Cloudflare access/ingress policy in addition to the MCP bearer credential. The MCP process itself remains loopback-only.

## Health

```text
GET /health
```

This endpoint is intentionally unauthenticated and contains only process/liveness state.

## MCP endpoint

With the current repository-pinned SDK, Streamable HTTP is served at:

```text
/mcp
```

The endpoint requires `Authorization: Bearer <AETHER_MCP_TOKEN>` for read/diagnostic access. The operator token can be used when mutation is explicitly intended.

## Verification registry

Verification IDs map to exact argv arrays. Example shape:

```json
{
  "gateway-tests": {
    "argv": ["python", "-m", "pytest", "aether-gateway/tests/test_living_machine_mcp.py"],
    "timeout_seconds": 120
  }
}
```

No string shell command is accepted by the MCP server.

## Windows / Linux / macOS

The MCP Python process is platform-neutral. Process supervision must follow the existing Aether host convention: Windows service/supervisor on Windows, systemd or the existing supervisor on Linux, and the normal local process manager on macOS. The MCP layer itself does not introduce a new service manager.

## Runtime proof

A production proof must show:

1. authenticated Streamable HTTP connection;
2. `aether_living_capabilities` discovery;
3. live workspace read/search/tree/hash;
4. runtime adapter and telemetry inspection;
5. bounded logs and Gateway health;
6. Git status/diff/log;
7. named verification execution and receipt;
8. mutation through the operator credential and GovernedActionPath;
9. verification failure causing the existing coding runtime rollback;
10. rollback receipt visible through MCP;
11. unauthenticated mutation denied;
12. path traversal, secret access, arbitrary shell, and public raw-port access denied.
