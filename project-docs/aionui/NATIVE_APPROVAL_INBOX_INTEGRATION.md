# Native AionUi Approval Inbox Integration

## Purpose

Provide one generic Founder/operator surface for all pending Aether actions without duplicating approval state, execution logic, credentials, or governance inside AionUi.

## Authority topology

```text
AionUi renderer
  → bounded typed IPC request
  → AionUi main process
      owns AETHER_OPERATOR_TOKEN
      sanitizes Gateway payloads
  → Aether Gateway /api/approvals
  → ApprovalInboxService
  → ApprovalCoordinator
  → TrustedApprovalInbox / GovernedActionPath
  → exact-once result receipt
```

AionUi is an operator shell. It is never the action, approval-state, identity, memory, or execution authority.

## Gateway contract

Endpoints:

```text
GET  /api/approvals/status
GET  /api/approvals?status=<status|all>
GET  /api/approvals/{approval_id}
POST /api/approvals/{approval_id}/approve
POST /api/approvals/{approval_id}/reject
```

Decision body:

```json
{
  "reason": "Founder reviewed the exact bounded action",
  "expected_action_hash": "<64-character SHA-256>"
}
```

The Gateway rejects a stale or mismatched operator view with HTTP `409` before action execution. Exact-once replay remains valid when the same completed decision is repeated.

## Renderer projection

The renderer receives:

- approval/action identifiers;
- exact action hash;
- status and timestamps;
- target and operation names;
- reason, risk, reversibility, and required scopes;
- argument key names only;
- a bounded safe target hint when available;
- allowlisted context identifiers;
- bounded result status/error, never result output.

The renderer does not receive:

- `AETHER_OPERATOR_TOKEN`;
- raw action bodies or `_body` values;
- arbitrary metadata;
- credential values;
- full command payloads;
- result output;
- Gateway filesystem or database access.

## Main-process service

`AetherApprovalService`:

- validates the Gateway URL;
- requires the operator token at construction;
- bounds timeouts and response text;
- validates status values and 64-character action hashes;
- projects only allowlisted fields;
- removes URL credentials, query strings, and fragments from target hints;
- returns `secret_values_exposed: false` on every renderer-facing snapshot/receipt;
- forwards exact hash-bound approve/reject requests.

## UI behavior

Route:

```text
/#/approvals
```

The page provides:

- pending/executing/consumed/approved/rejected/expired/all filters;
- status counts;
- bounded queue cards;
- detail inspection;
- full copyable action hash;
- risk/scope/reversibility/expiry visibility;
- explicit decision reason;
- approve/reject actions only while status is `pending`;
- replay receipt and operator-safe error visibility;
- ten-second polling with manual refresh.

### Browser Senses handoff

Browser Senses may present this native route with two non-secret query values:

```text
/#/approvals?approval_id=<approval-id>&action_hash=<full-sha256>
```

The renderer treats both values only as a selection request. It retrieves the
bounded approval projection through the existing main-process bridge and
selects nothing unless the returned full `action_hash` exactly matches the
handoff hash. The URL contains no operator token, raw action arguments, result
output, or decision authority. Approval still requires an explicit reason and
the existing hash-bound main-process decision call.

## Wiring

Use:

```text
aionui-integration/integration-snippets/approval-bridge-registration.ts.txt
aionui-integration/integration-snippets/approval-preload.ts.txt
aionui-integration/integration-snippets/approval-route.tsx.txt
aionui-integration/integration-snippets/approval-sidebar.tsx.txt
```

Environment remains main-process only:

```text
AETHER_GATEWAY_URL=http://127.0.0.1:8000
AETHER_OPERATOR_TOKEN=<stored outside renderer/source>
```

## Validation layers

Repository conformance:

```text
Gateway API tests
→ hash mismatch rejection
→ correct hash execution
→ exact-once replay
→ static integration security contract
→ Python/JSON compilation and parsing
```

Target AionUi conformance remains required after installation into a pinned AionUi v2 checkout:

```text
bun run lint
bun run test
bun run webui:prod:remote
package/build proof
manual Founder approval/rejection proof
renderer DevTools secret inspection
```

## Capability truth

Before target-checkout and Founder proof:

```text
Gateway shared service wiring     IMPLEMENTED / CI-CONFORMED after merge
AionUi integration source         IMPLEMENTED
Renderer security projection      STATIC-CONFORMED
Installed in pinned AionUi        NO
ACTIVE                            NO
FOUNDER-PROVEN                    NO
```
