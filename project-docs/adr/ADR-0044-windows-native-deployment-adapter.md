# ADR-0044 — Windows-Native Deployment Adapter

Status: Accepted for implementation before MVP v0.20  
Scope: Aether v0.19.2 operational patch, not a cognitive feature release

## Decision

Windows remains a first-class Aether target. Ubuntu is not a constitutional dependency. The v0.19.2 Soul, Mind, Gateway, memory, governance, runtime contracts, and browser-senses code remain shared. OS-specific lifecycle and ingress concerns belong under deployment adapters.

The existing Linux Docker/systemd stack is one adapter. A Windows-native adapter must provide equivalent process supervision, paths, ingress, logs, health evidence, backup, rollback, and uninstall behavior.

## Current evidence

The v0.19.2 release includes Windows `.bat` launchers, a documented Windows virtualenv installation path, `LOCALAPPDATA` path selection, `os.pathsep` use, and a cross-platform sidecar supervisor. The release does not contain Windows CI receipts or a Windows production-service pack.

Therefore:

- Windows Core/Gateway founder-alpha bring-up: deployment candidate.
- Windows one-domain persistent production stack: implementation required.
- Claim that Aether is Linux-only: rejected.
- Claim that Windows production is already verified: rejected.

## Required adapter components

1. `deploy/windows/` PowerShell installer and verifier.
2. Windows Service supervision for Gateway and LiveKit worker, using a service-aware wrapper.
3. Persistent AionUi standalone WebUI or supported desktop-bundled WebUI startup.
4. Caddy on `127.0.0.1:8080` as internal path router.
5. `cloudflared` native Windows service as public outbound ingress.
6. `C:\ProgramData\Aether` for service-owned mutable state; user-local data only for interactive alpha mode.
7. Platform-aware shell capability. The current `BashTool` name and POSIX tokenization must not define Windows semantics.
8. Windows CI matrix and live evidence receipts.

## Resource policy

Resource numbers are capacity recommendations, not architecture requirements.

- Founder-alpha Core/Gateway: 2 vCPU, 4 GB RAM, 20–40 GB disk is a reasonable starting envelope.
- AionUi build, realtime voice, multiple runtime CLIs, and concurrent evolution jobs: 4 vCPU, 8 GB RAM, and additional disk are recommended.
- Acceptance is based on measured health and latency, not a hardcoded VPS SKU.
