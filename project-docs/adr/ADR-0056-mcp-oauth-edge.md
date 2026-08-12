# ADR-0056 — Aether MCP OAuth Edge

- Status: Proposed
- Date: 2026-08-12
- Decision owner: Founder / Aether architecture
- Related: ADR-0053 (Founder Alpha Origin Authentication), ADR-0054 (Living
  Machine MCP), ADR-0055 (Principal Coordination Plane)

## Context

ADR-0054 established the Living Machine MCP with static Bearer token
(`AETHER_MCP_TOKEN`) authentication. This works for developer tools that
support raw Bearer auth (Codex, curl, opencode) — and Founder proof via Codex
0.147.0 is complete.

ChatGPT webchat (and other SOTA model frontends) connect to external MCP
servers through their built-in connector UI. OpenAI's connector builder
supports three auth modes: **OAuth**, **No Auth**, and **Mixed**. It does not
expose a raw Bearer token field. This means `AETHER_MCP_TOKEN` cannot be
entered directly into the ChatGPT MCP connector form.

Two workarounds exist but are both rejected:

1. **No Auth + Caddy token injection** — a public unauthenticated endpoint
   where Caddy injects the Bearer token upstream. Rejected: Living Machine MCP
   exposes filesystem read, runtime diagnostics, logs, and mutation submission.
   A publicly credential-bearing proxy with no client identity is an
   unacceptable security boundary for that capability surface.

2. **Fake OAuth metadata** — populate the OAuth form with dummy values.
   Rejected: ChatGPT performs a real OAuth handshake; fabricated endpoints
   cause handshake failure.

The correct path is a thin **OAuth Edge** service that speaks OAuth 2.0 to
ChatGPT while keeping `AETHER_MCP_TOKEN` as an internal upstream-only
credential. This edge also directly implements the principal identity
requirement from ADR-0055: each connected model arrives with a distinct
`principal_id` and scoped capabilities, not a shared master token.

## Decision

Add `aether-mcp-oauth-edge` as a new Python service (separate process, port
`:8789`) that acts as an OAuth 2.0 Authorization Server facade in front of the
Living Machine MCP.

### Architecture

```text
External model (ChatGPT / Claude / Gemini / ...)
    │
    │  OAuth 2.0 Authorization Code + PKCE
    ▼
https://aethers.my.id/oauth/*          ← Caddy route → :8789
    │
    │  validates principal, issues short-lived access token
    ▼
Aether MCP OAuth Edge  (:8789)
    │
    │  reverse-proxy MCP calls with:
    │    Authorization: Bearer AETHER_MCP_TOKEN
    │    X-Aether-Principal-Id: <principal_id>
    │    X-Aether-Principal-Scopes: <scope list>
    ▼
https://aethers.my.id/mcp              ← Living Machine MCP (:8787)
```

### OAuth Edge responsibilities

1. **Discovery endpoint** — `GET /.well-known/oauth-authorization-server`
   returns RFC 8414 metadata (authorization_endpoint, token_endpoint,
   registration_endpoint, scopes_supported).

2. **Client registration** — `POST /oauth/register` (RFC 7591 dynamic
   registration). Each AI principal registers once with a fixed `client_id`
   and optional `client_name`. Registration is gated: only pre-approved
   `client_id` values defined in `principal_registry.yaml` are accepted.

3. **Authorization endpoint** — `GET /oauth/authorize`. For ChatGPT's
   connector flow this is a Founder-mediated approval gate: the edge renders
   a minimal HTML confirmation page that the Founder approves via browser or
   Telegram inline button. No user password entry; the Founder IS the
   authorization authority.

4. **Token endpoint** — `POST /oauth/token`. Issues a short-lived JWT access
   token (default TTL: 3600s) signed with an edge-local HMAC-SHA256 secret.
   Token payload:

   ```json
   {
     "sub": "<principal_id>",
     "principal_id": "<principal_id>",
     "scopes": ["aether.read", "aether.diagnostic"],
     "iat": ...,
     "exp": ...,
     "jti": "<uuid>"
   }
   ```

5. **Refresh token** — issued alongside access token. TTL: 30 days. Stored
   in an edge-local SQLite db. Allows principals to renew without re-auth.

6. **MCP proxy** — `POST /mcp`, `GET /mcp`, `DELETE /mcp`. Validates the
   incoming access token, extracts `principal_id` and `scopes`, adds
   `X-Aether-Principal-*` headers, adds `Authorization: Bearer
   AETHER_MCP_TOKEN`, and reverse-proxies to `http://127.0.0.1:8787/mcp`.
   Scope enforcement: requests that require scopes beyond the token's grants
   are rejected with `403` before reaching the MCP server.

7. **Audit trail** — every token issuance, refresh, revocation, and MCP proxy
   call is written to an append-only JSONL audit log under `AETHER_HOME`.

### Principal registry

Principals are declared in a Founder-owned config file (not a runtime
datastore):

```yaml
# configs/principal_registry.yaml
principals:
  - id: chatgpt
    display_name: ChatGPT (OpenAI)
    client_id: aether-principal-chatgpt
    allowed_scopes: [aether.read, aether.diagnostic]
    mutation_authority: false

  - id: codex
    display_name: Codex (OpenAI CLI)
    client_id: aether-principal-codex
    allowed_scopes: [aether.read, aether.diagnostic, aether.mutate]
    mutation_authority: true

  - id: claude
    display_name: Claude (Anthropic)
    client_id: aether-principal-claude
    allowed_scopes: [aether.read, aether.diagnostic]
    mutation_authority: false
```

Adding a new principal requires a Founder-reviewed change to this file.
No principal gains capabilities beyond `allowed_scopes` regardless of what
they request in the OAuth flow.

### Scope definitions

| Scope | Permits |
|---|---|
| `aether.read` | file_read, git_status, logs_tail, runtime_status, runtime_adapters, service_status, health checks |
| `aether.diagnostic` | run_verification, runtime diagnostics, telemetry reads |
| `aether.mutate` | workspace_edit (operator token path), decide_and_resume |

`aether.mutate` requires `mutation_authority: true` in the principal registry
AND Founder approval at the authorization step. It is not issuable via
automated refresh.

### Token flow for ChatGPT connector

```text
1. Founder adds connector in ChatGPT UI:
   - MCP URL:  https://aethers.my.id/mcp
   - Auth:     OAuth
   - Auth URL: https://aethers.my.id/oauth/authorize
   - Token URL: https://aethers.my.id/oauth/token
   - Client ID: aether-principal-chatgpt
   - Scopes:   aether.read aether.diagnostic

2. ChatGPT initiates Authorization Code + PKCE flow.

3. OAuth Edge renders approval page → Founder approves (browser or Telegram).

4. Edge issues authorization code → ChatGPT exchanges for access + refresh token.

5. ChatGPT calls POST https://aethers.my.id/mcp (MCP initialize).

6. Edge validates token, injects headers, proxies to :8787.

7. Living MCP sees:
   Authorization: Bearer AETHER_MCP_TOKEN
   X-Aether-Principal-Id: chatgpt
   X-Aether-Principal-Scopes: aether.read aether.diagnostic

8. MCP tools execute with principal attribution on ActionProposal.metadata
   (per ADR-0055 requirement).
```

## Implementation plan

```text
IMPLEMENTED  → service boots, discovery + registration endpoints live
WIRED        → Caddy routes /oauth/* and /mcp through edge
CONFORMED    → token issuance, refresh, revocation verified by curl
ACTIVE       → ChatGPT connector configured, Scan Tools returns 22 tools
FOUNDER-PROVEN → ChatGPT calls runtime_status via edge; principal_id=chatgpt
               in audit log; ActionProposal carries principal attribution
```

Only `chatgpt` principal reaches FOUNDER-PROVEN before a second principal
is authorized, per ADR-0055 prerequisite §4.

## Security

- `AETHER_MCP_TOKEN` is never transmitted to or stored by any external
  principal. It lives only in the edge process environment and the upstream
  Authorization header.
- OAuth Edge HMAC secret is a separate credential (`AETHER_OAUTH_EDGE_SECRET`,
  minimum 32 bytes), stored in the same secrets facility as `AETHER_MCP_TOKEN`.
- The authorization approval gate ensures no principal can self-authorize.
  Founder is the sole approval authority.
- **Governance is authoritative and fail-closed (P0-remaining).** Every
  `/oauth/authorize` submits a governed `oauth.authorize` proposal into the
  shared Trusted Approval Inbox; if that submission fails, the authorization
  request is dropped and the consent page is not rendered (503). An
  authorization code is issued ONLY after the linked governed proposal is
  durably `APPROVED`. If the `mark_decision` call fails, or the proposal is not
  `APPROVED`, no code is issued. Governance unavailable never degrades into
  auto-approval.
- **Browser founder approval uses a short-lived signed session cookie, not a
  secret header.** The HTML approval page is a plain `POST` form and cannot
  carry `X-Aether-Operator-Token`. The Founder instead signs in once via
  `POST /oauth/login` (operator token), which mints an HttpOnly, `SameSite=Lax`,
  expiring cookie whose value is an HMAC-SHA256 signed payload carrying an
  explicit `purpose: founder-session` claim (so it can never be used as an MCP
  access token). The cookie is accepted only by the consent decision endpoints
  (`POST /oauth/approve`, `POST /oauth/reject`). API/CLI clients may still use
  the operator header.
- Short-lived access tokens (1 hour) limit blast radius of token leak.
- Refresh tokens are stored hashed (SHA-256) in the edge SQLite db; the
  plaintext is only returned once at issuance.
- Scope enforcement at the edge (before MCP) means the MCP server does not
  need to be scope-aware in this iteration.
- `aether.mutate` scope requires explicit Founder re-approval at every
  authorization; it is never auto-renewed via refresh.
- Audit JSONL is append-only and written to `AETHER_HOME` with the same
  ACL protection as other runtime artifacts (SYSTEM + Administrators only).
- Public endpoint remains `https://aethers.my.id/mcp` (through Caddy).
  The edge binds only to loopback (`:8789`). No raw port is exposed.

## Transport

- Service: Python (FastAPI), runs as a Windows service or manual process,
  same operational pattern as Living Machine MCP.
- Caddy routes: `/oauth/*` → `:8789/oauth/*`, `/mcp` → `:8789/mcp`
  (edge proxies onward to `:8787`). The existing `/mcp` direct route is
  REMOVED once the edge is ACTIVE to prevent bypass.
- The existing unauthenticated `/health/mcp` endpoint is preserved at
  `:8787` and re-exposed as `/health/mcp` through Caddy without going
  through the edge (health checks do not carry principal context).

## Non-goals

- No full identity provider (no OIDC userinfo, no user accounts).
- No principal-to-principal messaging.
- No capability granted by model name or role alone — only by Founder-approved
  registry entry.
- No change to the Living Machine MCP server itself in this ADR. The MCP
  server receives headers it does not yet act on; acting on them is a
  follow-on change covered by ADR-0055 implementation.

## Consequences

- ChatGPT (and any other OAuth-capable model frontend) can connect to Aether
  MCP without receiving `AETHER_MCP_TOKEN`.
- Each model has a distinct `principal_id` visible in audit logs and
  ActionProposal metadata, satisfying the ADR-0055 attribution requirement.
- `AETHER_MCP_TOKEN` remains a valid direct credential for developer tools
  (Codex, curl, opencode) that use it through existing config — no breaking
  change to those clients.
- Adding a new principal (Gemini, Claude, Qwen, etc.) requires only a registry
  entry change and a new connector configuration in that model's frontend; no
  code change to the edge or MCP server.
- The direct `/mcp` Caddy route (no edge) is decommissioned once the edge
  reaches ACTIVE status, closing the bypass path.
