# ADR-0054 — Aether Living Machine MCP Capability Plane

- Status: Implemented as a separate capability server
- Date: 2026-08-11
- Decision owner: Founder / Aether architecture
- Related: ADR-0051

## Decision

Add `Aether Living Machine MCP` as a separate MCP server over the existing Gateway composition root. It does not replace or weaken the read-only `Aether Operational MCP` baseline.

The living server exposes bounded READ, DIAGNOSTIC, VERIFY, and explicitly authorized MUTATE capabilities.

## Authority chain

```text
MCP client
  -> authenticated MCP ingress
  -> Living Machine MCP service
  -> existing Aether Gateway composition
  -> WorkspaceBinding / RuntimeAdapterRegistry / RuntimeTelemetry
  -> GovernedActionPath
  -> LocalStructuredCodingRuntimeAdapter / registered runtime body
```

The MCP layer never becomes a filesystem superuser and never bypasses Aether governance.

## Security

- `AETHER_MCP_TOKEN` authenticates normal read/diagnostic access.
- `AETHER_MCP_OPERATOR_TOKEN` authenticates the explicit mutation submission channel.
- Mutation creates an `ActionProposal` (never a fabricated `ActionApproval`). Because `write`/`execute` are in `action_policy.yaml` `approval_required` and the policy default is deny, the proposal is enqueued as a durable **pending-approval** record. Only a trusted human decision through the Trusted Approval Inbox / Telegram executes it via `GovernedActionPath`/`ActionGovernor`. The operator token authorizes submission only; it is never an approval source and cannot self-approve a mutation.
- File reads/search/glob/hash are constrained to repository, AETHER_HOME, and configured coding workspace roots.
- Secret-looking paths are denied by default.
- Symlink/junction escape is rejected after path resolution.
- Verification uses an explicit `AETHER_MCP_VERIFICATIONS` registry of argv arrays; arbitrary shell is not exposed.
- Git surface is read-only.
- Log output is bounded and redacted.
- No MCP credential is written to telemetry or responses.

## Transport

The repository is currently pinned to `mcp>=1.27,<2` by ADR-0051, so the living server uses the v1 SDK's Streamable HTTP implementation and stdio. The current MCP Python SDK stable line is v2 / protocol 2026-07-28. Migrating this repository to that line is a separate compatibility change and must preserve ADR-0051 regression proof; this implementation therefore does **not** claim 2026-07-28 protocol conformance yet.

Remote HTTP binds only to loopback. Cloudflare Tunnel/Caddy remains the public ingress boundary. A raw public MCP port is forbidden.

## Living machine vs GitHub

GitHub remains the versioned source of truth. Living MCP reports runtime truth: workspace state, adapter health, telemetry, service health, logs, and Git diagnostics. This allows an authorized agent to distinguish repository revision from deployed/runtime state.

## Mutation model

```text
READ -> UNDERSTAND -> PROPOSE -> GOVERNED APPLY -> VERIFY
                                             |
                                             +-- failure -> existing runtime rollback -> receipt
```

The MCP server does not implement a second filesystem writer. Structured edits remain the responsibility of `LocalStructuredCodingRuntimeAdapter`.
