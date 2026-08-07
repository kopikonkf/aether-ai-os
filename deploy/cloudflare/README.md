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

The Aether Caddy one-domain router listens on `http://127.0.0.1:8080`.
The tunnel forwards the public hostname to that local origin, so Caddy's
one-domain path rewriting remains authoritative.

## Founder Alpha authentication

The entire hostname is protected by Caddy basic auth (Founder Alpha single
operator). This is not Cloudflare Access; it is a deliberately narrow profile
accepted for a one-Founder deployment. Cloudflare Access is an optional future
upgrade.

- Username: `founder`
- Password: random >= 32 bytes, stored only in Dee's password manager
- Hash: bcrypt cost 14
- Plaintext is never stored on the VPS and never appears in receipts/logs

The bcrypt hash is generated interactively (never via command-line argument):

```powershell
$hash = & "C:\Program Files\Caddy\caddy.exe" hash-password --algorithm bcrypt --bcrypt-cost 14
```

The installer writes the ACL-protected fragment
`C:\ProgramData\Aether\caddy\founder-auth.caddy` and strips the `Authorization`
header before forwarding to any upstream.

## Windows Host Install

Provision the Cloudflare Tunnel and DNS route in Cloudflare first. Copy the
Cloudflare credentials JSON to a locked-down host path, then run elevated
PowerShell:

```powershell
.\deploy\cloudflare\install-cloudflare-ingress.ps1 `
  -PublicHostname "aether.example.com" `
  -TunnelId "<cloudflare-tunnel-id>" `
  -CredentialsFile "C:\ProgramData\Aether\cloudflare\<cloudflare-tunnel-id>.json" `
  -CaddyPath "C:\Program Files\Caddy\caddy.exe" `
  -FounderAuthFile "C:\ProgramData\Aether\caddy\founder-bcrypt.env" `
  -Start
```

The installer creates:

- `AetherCaddy` Windows service (Caddy v2 one-domain router on `:8080`);
- `AetherCloudflareTunnel` Windows service;
- `C:\ProgramData\Aether\caddy\Caddyfile`;
- `C:\ProgramData\Aether\caddy\founder-auth.caddy` (ACL-protected, bcrypt only);
- `C:\ProgramData\Aether\cloudflare\config.yml`;
- `C:\ProgramData\Aether\cloudflare\cloudflare-ingress-manifest.json`.

It never writes tunnel tokens, credentials JSON contents, `.env`, request
headers, the founder username, or the bcrypt hash to receipts.

## Probe

```powershell
# unauthenticated: expect 401 on every route
.\deploy\cloudflare\probe-cloudflare-ingress.ps1 `
  -BaseUrl "https://aether.example.com" -AuthMode "CaddyBasic"

# authenticated: expect 2xx on every route
.\deploy\cloudflare\probe-cloudflare-ingress.ps1 `
  -BaseUrl "https://aether.example.com" `
  -AuthMode "CaddyBasic" -Credential (Get-Credential)
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

Public routes are authenticated by Caddy basic auth. Unauthenticated requests
return `401` + `WWW-Authenticate: Basic`; authenticated requests return the
real application.

| Route | Meaning |
|---|---|
| `/health` | public health (authenticated) |
| `/aether/api/status` | Gateway API through one-domain rewrite |
| `/api/browser-senses/status` | browser senses status |
| `/senses` | public senses UI shell |

Internal health on loopback (`http://127.0.0.1:8000/health`) stays unauthenticated
for SCM recovery and the AetherWatchdog; there is no operational need to open
public `/health` unauthenticated.

`/#/senses` is a browser-side AionUi route and should be checked in a browser
after the HTTP probes pass.

## Boundary

This PR can only make Cloudflare ingress source-present. `WIRED`, `ACTIVE`, and
`FOUNDER-PROVEN` require a real host tunnel, public HTTPS probes, and Founder
acceptance against those receipts.
