# Windows Service Heartbeat and Watchdog

## Decision

Aether on Windows VPS must be supervised by the operating system, not by an open
terminal or a persistent ChatGPT/Codex session.

This source slice adds a native Windows service harness:

    AetherGateway
      -> aether_gateway.api.server
      -> http://127.0.0.1:8000/health

    AetherWatchdog
      -> poll /health
      -> append heartbeats.jsonl
      -> restart AetherGateway after bounded consecutive failures

AetherSenseWorker is optional and only installed when LiveKit is configured and
explicitly requested.

## Runtime State

The Windows service path explicitly sets:

    AETHER_HOME=C:\ProgramData\Aether

This keeps service-owned mutable state separate from immutable release source
under C:\Aether\releases\....

## Receipt Files

    C:\ProgramData\Aether\services\heartbeats.jsonl
    C:\ProgramData\Aether\services\service-events.jsonl
    C:\ProgramData\Aether\services\service-manifest.json

Receipts must not contain secrets, environment dumps, .env contents, tokens,
public IP addresses, or raw logs.

## Capability State

This branch can only advance the slice to source-level IMPLEMENTED.

Host proof is still required for:

    WIRED
    CONFORMED
    ACTIVE
    FOUNDER-PROVEN

Minimum host proof:

    Get-Service AetherGateway,AetherWatchdog
    Invoke-RestMethod http://127.0.0.1:8000/health
    Get-Content C:\ProgramData\Aether\services\heartbeats.jsonl -Tail 3

Service restart proof should show a controlled Gateway restart and a later
healthy heartbeat receipt. Cloudflare ingress, migrated AETHER_HOME, and
Founder acceptance remain separate gates.