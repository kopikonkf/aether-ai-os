# Founder Acceptance

Date: 2026-07-31
Status: source-present, signed Founder record pending

## Decision

Founder acceptance is an explicit runtime gate, not a hardcoded status flag.
`aether-body` can generate an acceptance packet from current runtime evidence
and can persist a signed Founder record under `AETHER_HOME`. The body reports
`founder_proven: true` only after that record exists.

## Runtime Routes

| Route | Purpose |
|---|---|
| `/v1/body/founder/acceptance` `GET` | Generate latest acceptance packet |
| `/v1/body/founder/acceptance` `POST` | Record explicit Founder acceptance |
| `/v1/body/conformance` | Reads latest acceptance state |
| `/v1/body/mcp/status` | Read local MCP activation state |
| `/v1/body/mcp/activate` | Write MCP activation record |

## Evidence Files

| File | Meaning |
|---|---|
| `$AETHER_HOME/runtime/founder_acceptance/latest_packet.json` | Latest generated packet |
| `$AETHER_HOME/runtime/founder_acceptance/latest_acceptance.json` | Latest signed acceptance record |
| `$AETHER_HOME/runtime/founder_acceptance/acceptance.jsonl` | Append-only acceptance log |
| `$AETHER_HOME/runtime/body/receipts.jsonl` | Includes `founder.acceptance.recorded` |
| `$AETHER_HOME/runtime/mcp/latest_activation.json` | Latest MCP activation record |
| `$AETHER_HOME/runtime/mcp/manifest.json` | MCP manifest snapshot |

## Acceptance Criteria

Required:

- runtime body conformance;
- body receipt path has evidence;
- TTS fallback proof receipt and audio artifact;
- AionUi/Senses public health evidence;
- Aether MCP activation evidence;
- Founder attestation.

Optional host/live proof included in the packet:

- Cloudflare/one-domain public HTTPS probe;
- credentialed Google Cloud TTS live audition.

## CLI

```bash
export AETHER_HOME=/opt/aether/home
export AETHER_MIND_URL=http://127.0.0.1:8765

aether-founder-acceptance status
```

Host evidence may be supplied as JSON:

```json
{
  "browser_senses_status": {
    "status": "ok",
    "gateway": {
      "public_routes": ["/health", "/api/browser-senses/status", "/senses"]
    }
  },
  "mcp_activation": {
    "activated": true,
    "tools": [
      "aether_who_am_i",
      "aether_north_star_evaluate",
      "aether_believe",
      "aether_sleep",
      "aether_run_task"
    ]
  },
  "public_host_probe": {
    "status": "ok",
    "url": "https://aether.example.com/health"
  }
}
```

Then sign:

```bash
aether-founder-acceptance accept \
  --founder-id Dee \
  --attestation "I accept this Aether founder acceptance packet for the current local batch." \
  --evidence-json /path/to/founder-evidence.json
```

Use `--allow-pending-evidence` only when the Founder is explicitly accepting
remaining host/live gaps as known boundaries.

## Boundary

This slice does not forge Founder acceptance. It adds the evidence packet,
sign-off path, acceptance receipt, and body conformance wiring. Until the
Founder signs on the host or through the body endpoint, `founder_proven` remains
false.
