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
| AetherWatchdog | Writes heartbeat receipts and performs bounded Gateway restarts | Automatic |

## Install

Run from an elevated PowerShell session in the immutable release root:

    .\deploy\windows\install-aether-services.ps1 -Start

Optional LiveKit worker:

    .\deploy\windows\install-aether-services.ps1 -InstallSenseWorker -Start

Optional explicit Python path:

    .\deploy\windows\install-aether-services.ps1 -PythonPath C:\Aether\releases\Aether_OS_v0.19.2-founder-alpha-frozen.2\.venv\Scripts\python.exe -Start

## Receipts

The watchdog writes secret-safe JSONL receipts:

    C:\ProgramData\Aether\services\heartbeats.jsonl

The service runner writes child process events:

    C:\ProgramData\Aether\services\service-events.jsonl

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

## Uninstall

    .\deploy\windows\uninstall-aether-services.ps1

Runtime state is preserved. Delete C:\ProgramData\Aether only after a backup and
explicit Founder approval.