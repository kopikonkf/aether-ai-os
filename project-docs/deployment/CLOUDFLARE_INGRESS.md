# Cloudflare Ingress

## Decision

Aether public ingress should be Cloudflare Tunnel for the Founder host when
ports 80/443 should not be directly exposed. The tunnel is an ingress body, not
an authority layer: Aether Gateway still owns cognition, memory, governance, and
runtime receipts.

## Source Components

| Path | Purpose |
|---|---|
| `deploy/cloudflare/cloudflared-aether.yml` | tunnel config template |
| `deploy/cloudflare/install-cloudflare-ingress.ps1` | Windows service installer |
| `deploy/cloudflare/probe-cloudflare-ingress.ps1` | public HTTPS probe and receipt writer |
| `aether-cloudflare-ingress` | cross-platform status/probe/record CLI |
| `$AETHER_HOME/runtime/ingress/latest_cloudflare_probe.json` | latest runtime evidence |

## Required Host Proof

```powershell
Get-Service AetherGateway,AetherWatchdog,AetherCloudflareTunnel
Invoke-RestMethod http://127.0.0.1:8000/health
.\deploy\cloudflare\probe-cloudflare-ingress.ps1 -BaseUrl "https://aether.example.com"
Get-Content C:\ProgramData\Aether\runtime\ingress\latest_cloudflare_probe.json
```

Required public routes:

```text
https://aether.example.com/health
https://aether.example.com/aether/api/status
https://aether.example.com/api/browser-senses/status
https://aether.example.com/senses
```

Browser proof should also open `https://aether.example.com/#/senses`; the hash
route is client-side and is not an HTTP request path.

## Safety

- Do not commit tunnel credentials JSON or connector tokens.
- Do not expose port 8000 directly.
- The tunnel service command uses a config file and does not place a token in
  the Windows service command line.
- Receipts store status, routes, latencies, and hashed tunnel identity only.

## Capability State

This source slice advances Cloudflare ingress to `IMPLEMENTED`.

Host proof is still required for:

```text
WIRED
CONFORMED
ACTIVE
FOUNDER-PROVEN
```
