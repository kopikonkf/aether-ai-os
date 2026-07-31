# Cloudflare Ingress

This source slice adds Cloudflare Tunnel ingress for the one-domain Founder host.
It keeps local services loopback-only and uses Cloudflare as the public edge.

## Topology

```text
Cloudflare edge
  -> cloudflared tunnel service
  -> local Caddy one-domain router
  -> AionUi on 127.0.0.1:25808
  -> Aether Gateway on 127.0.0.1:8000
```

The default tunnel origin is `http://127.0.0.1:80` so the existing Caddy
one-domain path rewriting remains authoritative.

## Windows Host Install

Provision the Cloudflare Tunnel and DNS route in Cloudflare first. Copy the
Cloudflare credentials JSON to a locked-down host path, then run elevated
PowerShell:

```powershell
.\deploy\cloudflare\install-cloudflare-ingress.ps1 `
  -PublicHostname "aether.example.com" `
  -TunnelId "<cloudflare-tunnel-id>" `
  -CredentialsFile "C:\ProgramData\Aether\cloudflare\<cloudflare-tunnel-id>.json" `
  -Start
```

The installer creates:

- `AetherCloudflareTunnel` Windows service;
- `C:\ProgramData\Aether\cloudflare\config.yml`;
- `C:\ProgramData\Aether\cloudflare\cloudflare-ingress-manifest.json`.

It never writes tunnel tokens, credentials JSON contents, `.env`, or request
headers to receipts.

## Probe

```powershell
.\deploy\cloudflare\probe-cloudflare-ingress.ps1 `
  -BaseUrl "https://aether.example.com"
```

Receipts:

```text
C:\ProgramData\Aether\runtime\ingress\latest_cloudflare_probe.json
C:\ProgramData\Aether\runtime\ingress\cloudflare-probes.jsonl
```

The same evidence can be recorded through the package CLI:

```bash
aether-cloudflare-ingress status
aether-cloudflare-ingress probe --base-url https://aether.example.com
```

## Required Public Checks

| Route | Meaning |
|---|---|
| `/health` | cheap public health |
| `/aether/api/status` | Gateway API through one-domain rewrite |
| `/api/browser-senses/status` | browser senses status |
| `/senses` | public senses UI shell |

`/#/senses` is a browser-side AionUi route and should be checked in a browser
after the HTTP probes pass.

## Boundary

This PR can only make Cloudflare ingress source-present. `WIRED`, `ACTIVE`, and
`FOUNDER-PROVEN` require a real host tunnel, public HTTPS probes, and Founder
acceptance against those receipts.
