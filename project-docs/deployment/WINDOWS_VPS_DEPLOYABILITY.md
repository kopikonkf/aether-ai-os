# Windows VPS Deployability Decision — Aether OS v0.19.2

## Decision

**No: the complete v0.19.2 one-domain production stack is not directly deployable to a standard Windows Server VPS using the artifacts currently shipped.**

**Yes: Aether Core and Aether Gateway can be installed and exercised natively on Windows for local first pulse and development.**

These are separate support claims.

## Source audit matrix

| Component | Native Windows code path | Shipped production orchestration | Decision |
|---|---:|---:|---|
| Aether Core wheel | Yes (`py3-none-any`) | Manual/venv | Supported for local/dev |
| Aether Gateway wheel | Yes (`py3-none-any`) | Manual/venv | Supported for local/dev |
| Founder init/doctor/smoke | Yes | `START_AETHER.bat`, Python utility | Supported |
| Persistent Gateway service | Code can run | No Windows service definition | Not production-conformed |
| Aether Sense Worker | Python path exists | Linux container/systemd only | Not Windows-release-verified |
| AionUi sidecar integration | Upstream has Windows support | Aether image is Linux `node:bookworm` | Not directly shipped |
| Caddy routing | Cross-platform upstream binary exists | Release config assumes Linux/container service | Adapter missing |
| Cloudflare connector | Cross-platform upstream binary exists | No Windows Aether service artifact | Adapter missing |
| Full Compose stack | Linux images | Linux container runtime required | Not direct on Windows Server |
| Restart/log/backup lifecycle | Possible | systemd/Docker artifacts only | Adapter missing |

## Why this is not merely an installer issue

The production release contract includes process supervision, boot persistence, health checks, network isolation, secret injection, volume persistence, logs, rollback, and deterministic AionUi integration. Running `aether-gateway` in a Windows terminal proves the Core/Gateway path, not the complete production body.

## Canonical host for tonight

Provision:

```text
OS:       Ubuntu 24.04 LTS x86_64
CPU:      4 vCPU minimum
Memory:   8 GB RAM minimum
Storage:  80 GB NVMe minimum
Network:  outbound Internet; inbound SSH only
Access:   non-root sudo user with SSH key
```

The Founder can still operate it through GUI tooling from Windows: the VPS provider console, VS Code Remote SSH, or another SSH client. The server OS does not determine the daily Aether interaction surface; AionUi in the browser does.

## If Windows Server remains mandatory

Create a separate operational slice, tentatively `v0.19.2.1-windows-service-adapter`, containing at least:

1. PowerShell installer and preflight.
2. Windows service wrappers for Gateway, Sense Worker, AionUi, Caddy, and cloudflared.
3. Native persistent data paths and ACLs.
4. Windows firewall policy.
5. Log rotation and crash restart policy.
6. AionUi integrated Windows build or stable standalone WebUI service.
7. Backup/restore and uninstall paths.
8. End-to-end browser microphone/camera verification on Windows Server.

Until those artifacts pass, Windows VPS is a development experiment rather than the canonical Founder Alpha deployment.
