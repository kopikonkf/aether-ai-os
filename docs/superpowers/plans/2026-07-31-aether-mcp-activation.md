# Aether MCP Activation

Date: 2026-07-31
Status: source-present, activation proof pending

## Decision

Expose a minimal Aether MCP server that activates against the local Aether mind
daemon, persists activation state under `AETHER_HOME`, and fails safe when the
mind is unreachable. The first batch of tools is the narrow body/mind surface
needed for v0.20:

- `aether_who_am_i`
- `aether_north_star_evaluate`
- `aether_believe`
- `aether_sleep`
- `aether_run_task`

## Runtime Paths

| Path | Purpose |
|---|---|
| `/v1/body/mcp/status` | Read local activation state |
| `/v1/body/mcp/activate` | Write activation manifest and receipt |
| `$AETHER_HOME/runtime/mcp/manifest.json` | MCP manifest snapshot |
| `$AETHER_HOME/runtime/mcp/latest_activation.json` | Latest activation record |
| `$AETHER_HOME/runtime/mcp/receipts.jsonl` | Append-only MCP receipts |

## CLI

```bash
export AETHER_HOME=/opt/aether/home
export AETHER_MIND_URL=http://127.0.0.1:8765

aether-mcp status
aether-mcp activate
```

StdIO clients can launch the same entrypoint without arguments:

```bash
aether-mcp
```

## Evidence

Activation is considered present when the activation record includes the
required tool set and the body sees it in `AETHER_HOME`.

## Boundary

This slice does not claim hosted MCP marketplace wiring or remote tool
registration. It gives the local activation contract, the JSON-RPC handshake,
and receipts that Founder acceptance can read.
