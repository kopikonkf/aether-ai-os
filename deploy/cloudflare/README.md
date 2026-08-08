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

The Aether Caddy one-domain router listens on `:8080` with `bind 127.0.0.1`
(host-agnostic listener, loopback-bound: any Host header on the loopback origin
is routed through the founder auth). The tunnel forwards the public hostname
(`aethers.my.id` / `www.aethers.my.id`) to that local origin with the original
Host header preserved, so Caddy's one-domain path rewriting and Basic auth
remain authoritative even though the Host is a domain, not `127.0.0.1`.

## Founder Alpha authentication

The entire hostname is protected by Caddy basic auth (Founder Alpha single
operator). This is not Cloudflare Access; it is a deliberately narrow profile
accepted for a one-Founder deployment. Cloudflare Access is an optional future
upgrade.

- Username: `founder`
- Password: random >= 32 bytes, stored only in Dee's password manager
- Hash: bcrypt cost 14
- Plaintext is never stored on the VPS and never appears in receipts/logs

The bcrypt hash is generated interactively (never via command-line argument) and
staged in a **temporary, inheritance-protected file** that the installer consumes
and then deletes. Only the ACL-protected canonical fragment
`C:\ProgramData\Aether\caddy\founder-auth.caddy` persists — no `.env` file is
used, and no second hash-bearing file is left behind:

```powershell
# Stage the transient hash input under a protected temp path (never .env).
$tmpHash = "$env:TEMP\aether-founder-bcrypt.txt"
# Generate the hash interactively (no --plaintext on the command line):
#   C:\Program Files\Caddy\caddy.exe hash-password --algorithm bcrypt --bcrypt-cost 14
#   (typed at the prompt) then save the printed hash to $tmpHash.
$hash = (Read-Host "Paste the bcrypt hash" ) | ForEach-Object { $_ -replace '[\r\n]', '' }
$hash | Set-Content -LiteralPath $tmpHash -Encoding utf8 -NoNewline
# Lock the input down (SYSTEM + Administrators only) so the installer may read it
# exactly once and then remove it:
icacls $tmpHash /inheritance:r /grant:r "SYSTEM:F" "Administrators:F"
```

The installer writes the ACL-protected fragment
`C:\ProgramData\Aether\caddy\founder-auth.caddy`, strips the `Authorization`
header before forwarding to any upstream, verifies the temporary hash input's
DACL before reading it, and removes that temporary input after the fragment is
safely written — so only the protected canonical fragment remains as hash
storage.

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
  -FounderUsername "founder" `
  -FounderAuthFile "$env:TEMP\aether-founder-bcrypt.txt" `
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

Passwords are never accepted on the command line. Supply credentials either as
an in-memory `PSCredential` object or by reading the password from stdin.

One complete CaddyBasic invocation proves the whole receipt: unauthenticated
denial, correct-credential 2xx, wrong-credential denial, and the echo-derived
`authorization_forwarded_to_upstream=false` (header strip observed at the
upstream). When `-EchoRoute` is given, the probe sends one authenticated request
through Caddy to that route; the production Caddyfile forwards it to the real
upstream, so on a proof host the route must point at a temporary echo upstream
that echoes the headers it actually received. The echo route is proof-only and
is removed (the production Caddyfile keeps no public echo endpoint).

```powershell
# Complete proof, passwords from PSCredential objects (nothing on the CLI):
$secure   = Read-Host -AsSecureString "Founder password"
$cred     = [pscredential]::new("founder", $secure)
$wrongSec = Read-Host -AsSecureString "Deliberately wrong password"
$wrong    = [pscredential]::new("founder", $wrongSec)
.\deploy\cloudflare\probe-cloudflare-ingress.ps1 `
  -BaseUrl "https://aether.example.com" `
  -AuthMode "CaddyBasic" `
  -Credential $cred -WrongCredential $wrong `
  -EchoRoute "/__echo"

# Equivalent proof with passwords read from stdin (two lines: correct, wrong):
"s3cr3t-founder`nwrong-pass" | .\deploy\cloudflare\probe-cloudflare-ingress.ps1 `
  -BaseUrl "https://aether.example.com" `
  -AuthMode "CaddyBasic" `
  -CredentialUsername "founder" -CredentialPasswordStdin `
  -WrongCredentialUsername "founder" -WrongCredentialPasswordStdin `
  -EchoRoute "/__echo"
```

On a live public host (HTTPS + tunnel service running + proof echo route present)
the return receipt is `status: ok` with `unauthenticated_all_denied=true`,
`authenticated_all_ok=true`, `invalid_credentials_all_denied=true`,
`header_strip_observed=true`, `authorization_forwarded_to_upstream=false`, and
`secret_values_exposed=false`.

Credential surfaces are rejected unless complete: a username without a password
source, or a password source without a username, is refused before any request.
Wrong-credential probes use `-WrongCredential` / `-WrongCredentialUsername`
with `-WrongCredentialPasswordStdin`.

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
