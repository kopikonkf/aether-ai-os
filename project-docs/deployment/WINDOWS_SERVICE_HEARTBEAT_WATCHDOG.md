# Windows Service Heartbeat and Watchdog

## Decision

Aether on Windows VPS must be supervised by the operating system, not by an open
terminal or a persistent ChatGPT/Codex session.

The Windows adapter uses an SCM-compatible Python service host. The host calls
the Windows service dispatcher, reports lifecycle state, and owns its supervised
child process tree in a kill-on-close Job Object. PowerShell runners remain
implementation children; they are not registered directly as Windows services.

    AetherGateway service
      -> SCM-compatible service host
      -> aether-service-runner.ps1
      -> aether_gateway.api.server
      -> http://127.0.0.1:8000/health

    AetherWatchdog service (no Gateway service dependency)
      -> SCM-compatible service host
      -> aether-watchdog.ps1
      -> poll /health
      -> append heartbeats.jsonl
      -> start or restart AetherGateway after bounded failures

AetherSenseWorker is optional and only installed when LiveKit is configured and
explicitly requested.

The watchdog must remain independently startable while `AetherGateway` is
stopped. This is required for recovery from a total Gateway service failure.
Installer reconciliation clears historical watchdog dependencies.

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
public IP addresses, raw logs, or the supervised child command line.

## Capability State

Source and Linux CI can only advance this repair to IMPLEMENTED.

Host proof is still required for:

    WIRED
    CONFORMED
    ACTIVE
    FOUNDER-PROVEN

Minimum host proof:

    Get-Service AetherGateway,AetherWatchdog
    Invoke-RestMethod http://127.0.0.1:8000/health
    Get-Content C:\ProgramData\Aether\services\heartbeats.jsonl -Tail 3

Service recovery proof must demonstrate that:

1. both services reach `Running` under SCM;
2. the watchdog has no dependency on the Gateway;
3. a controlled total Gateway stop is observed;
4. the independently running watchdog starts the Gateway again;
5. a later heartbeat is healthy and bound to the exact deployed commit.

Cloudflare ingress, migrated AETHER_HOME, and Founder acceptance remain separate
gates.
