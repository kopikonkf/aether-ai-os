# Aether Windows Services

This folder contains the source-level Windows service harness for the persistent
Aether Gateway slice.

It installs OS-owned services. It does not install ChatGPT desktop, Codex, or any
model-provider credential as a persistent daemon.

## Services

| Service | Purpose | Startup |
|---|---|---|
| AetherGateway | Runs the Gateway API with AETHER_HOME=C:\ProgramData\Aether | Automatic |
| AetherSenseWorker | Optional LiveKit Sense Worker | Automatic when installed |
| AetherWatchdog | Writes heartbeat receipts and performs bounded Gateway recovery | Automatic; independent of Gateway |

`aether-windows-service.py` is the SCM-facing service process. It connects to
Windows Service Control Manager, reports service lifecycle state, and supervises
the existing PowerShell runner or watchdog inside a kill-on-close Job Object.
PowerShell is a supervised child process; it is not registered directly as the
service binary.

The watchdog deliberately has no service dependency on `AetherGateway`. This
allows it to start and recover the Gateway when the Gateway service is fully
stopped.

## Install

Run from an elevated PowerShell session in the immutable release root:

    .\deploy\windows\install-aether-services.ps1 -Start

Optional LiveKit worker:

    .\deploy\windows\install-aether-services.ps1 -InstallSenseWorker -Start

Both the Gateway and the LiveKit Sense Worker read their credentials from a
canonical protected secret file at `C:\ProgramData\Aether\secrets\senses-livekit.env`.
Provision it from a protected source env file OUTSIDE the repo (so rotated
credentials never need to be stored in the dev tree):

    .\scripts\provision-sense-worker-secrets.ps1 -SourceEnvPath C:\ProgramData\Aether\secrets\source-livekit.env

The source file must be DACL-protected (SYSTEM + Administrators only, no
inheritance) and must not be a reparse point. The provisioner writes a unique
protected temp file, exact-verifies it, and atomically replaces the canonical
file via `File.Replace`. Secrets are never accepted as command-line arguments.

The service runner injects a role-scoped allowlist of keys into each service
process (gateway: `LIVEKIT_URL/API_KEY/API_SECRET/AGENT_NAME/AETHER_SENSE_WORKER_TOKEN`;
worker: same set). The runner refuses to load an unprotected file, an unexpected
ACE, or a malformed/partial file, and never logs raw values. Never copy `.env`
into a release, and never set LiveKit credentials as Machine-scope environment
variables.

Optional explicit Python path:

    .\deploy\windows\install-aether-services.ps1 -PythonPath C:\Aether\releases\Aether_OS_v0.19.2-founder-alpha-frozen.2\.venv\Scripts\python.exe -Start

The installer is idempotent for existing service registrations. It rewrites the
binary path, startup mode, recovery actions, and dependency configuration. In
particular, reinstalling clears any historical Gateway dependency from the
watchdog.

## Receipts

The watchdog writes secret-safe JSONL receipts:

    C:\ProgramData\Aether\services\heartbeats.jsonl

The service host and child runner write lifecycle events:

    C:\ProgramData\Aether\services\service-events.jsonl

The service host never records the child command or its arguments.

## Verification

    Get-Service AetherGateway,AetherWatchdog
    Invoke-RestMethod http://127.0.0.1:8000/health
    Get-Content C:\ProgramData\Aether\services\heartbeats.jsonl -Tail 3

Expected health payload shape:

    {
      "status": "ok",
      "service": "aether-gateway",
      "aether_home": "C:\ProgramData\Aether"
    }

SCM conformance and watchdog recovery still require a live Windows host proof.
Linux CI validates source contracts and argument boundaries only.

## Uninstall

    .\deploy\windows\uninstall-aether-services.ps1

Runtime state is preserved. Delete C:\ProgramData\Aether only after a backup and
explicit Founder approval.
