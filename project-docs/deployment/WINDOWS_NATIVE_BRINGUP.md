# Windows-Native Founder Alpha Bring-Up

This pack proves the Windows-native Core/Gateway path without Docker, WSL, systemd, or SSH.

## Supported now

- secure local `.env` creation;
- Python 3.11+ virtual environment;
- installation of the v0.19.2 wheels;
- deterministic doctor and 13-step first pulse;
- persistent Aether data under a Windows path;
- local Gateway startup and `/api/status` evidence;
- browser `/senses` on localhost.

## Not claimed yet

- Windows Service auto-start/restart;
- integrated AionUi persistence;
- real Cloudflare Tunnel route;
- real LiveKit microphone-to-speech turn;
- Windows conformance receipt for Codex/Claude/Gemini/OpenCode;
- production backup and rollback.

## Run on the Windows VPS

Open PowerShell in the extracted Aether v0.19.2 release directory.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\AETHER_WINDOWS_READINESS.ps1
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
```

Open:

```text
http://127.0.0.1:8000/senses
```

Status:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Status
```

Stop:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Stop
```

Evidence files:

```text
windows-readiness.json
.aether-windows\windows-alpha-evidence.json
.aether-windows\logs\gateway.stdout.log
.aether-windows\logs\gateway.stderr.log
```

Before sharing evidence, redact tokens, API keys, tunnel credentials, hostnames if private, and user filesystem names if sensitive.
