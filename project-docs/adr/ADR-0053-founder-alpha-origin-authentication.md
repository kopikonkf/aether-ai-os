# ADR-0053 — Founder Alpha Origin Authentication

## Status

Accepted for Founder Alpha.

## Context

The Aether one-domain host must not be reachable anonymously. The public
entry point terminates at Cloudflare Tunnel, which forwards to a local Caddy
router, which routes to Aether Gateway and optionally AionUi.

The previous session proposed Cloudflare Access as the mandatory auth layer.
Enabling Zero Trust Free currently requires onboarding that asks for a payment
method. Dee does not want to add billing details and explicitly declined to
activate Zero Trust now. Cloudflare itself documents that Free Zero Trust
onboarding still collects payment details even though nothing is billed.

This ADR replaces Cloudflare Access with a Caddy Basic Auth profile for the
Founder Alpha single-operator deployment. Basic Auth is not equivalent to
Access (no SSO, no Identity Provider, no per-app policies). It is accepted as
a deliberately narrow security profile for one Founder on one host until a
future Access upgrade.

Cloudflare Access is moved to `OPTIONAL_FUTURE_UPGRADE`, not a gate.

## Decision

Production Founder Alpha authentication:

```text
Cloudflare Tunnel
→ Caddy basic_auth (entire hostname)
→ Gateway / AionUi
```

| Element | Decision |
|---|---|
| Username | `founder` |
| Password | Random, minimum 32 bytes; stored only in Dee's password manager |
| Hash | bcrypt cost 14 |
| Plaintext on VPS | Forbidden |
| `.env` | Not used |
| Config storage | ACL-protected Caddy fragment |
| Scope | All paths, including `/`, `/health`, API, `/senses` |
| Upstream | `Authorization` header must be stripped before forwarding |
| Service identity | `AetherCaddy` stays `LocalSystem` |
| Future Access | May replace Basic Auth later, after Dee authorizes billing |

## Hash generation

Caddy supports bcrypt natively:

```powershell
$hash = & "C:\Program Files\Caddy\caddy.exe" hash-password --algorithm bcrypt --bcrypt-cost 14
```

Always run interactively (`--plaintext` is the default typed as a prompt; do
not pass the password as a command-line argument) so it does not appear in
command history.

## Configuration layout

```text
C:\ProgramData\Aether\caddy\Caddyfile
C:\ProgramData\Aether\caddy\founder-auth.caddy
```

`founder-auth.caddy`:

```caddyfile
basic_auth bcrypt "Aether Founder Alpha" {
    founder <BCRYPT-HASH>
}
```

`founder-auth.caddy` inherits the protected AETHER_HOME DACL:

```text
SYSTEM         FullControl
Administrators FullControl
Inheritance    Protected
Other SID      None
```

The bcrypt hash must never appear in manifests, receipts, logs, PRs, or GitHub
comments.

## `/health` contract

Public `/health` is authenticated:

```text
https://aethers.my.id/health without credentials -> 401
https://aethers.my.id/health with credentials    -> 200
```

Internal health stays open on loopback:

```text
http://127.0.0.1:8000/health -> 200
```

SCM recovery and the AetherWatchdog must use the internal health URL so there
is no operational reason to open public `/health`.

## Consequences

- Gateway must be reachable on loopback only (`:8000`).
- Caddy strips `Authorization` before forwarding to Gateway/AionUi.
- Receipts must not contain username, hash, password, or `Authorization`
  values.
- Basic Auth provokes `401` + `WWW-Authenticate: Basic` on unauthenticated
  requests over public HTTPS.