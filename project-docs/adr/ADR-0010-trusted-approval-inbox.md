# ADR-0010 — Trusted Approval Inbox

**Status:** Accepted  
**Release:** MVP v0.5

## Decision

Every action that receives `approval-required` is persisted in a local approval inbox instead of being discarded or executed through an ad hoc callback.

The inbox stores:

- a random approval ID;
- the original action ID;
- a canonical SHA-256 hash of execution semantics;
- the complete provider-neutral `ActionProposal`;
- request channel and requester context;
- request and expiry timestamps;
- decision identity, reason, channel, and time;
- optional cognitive continuation;
- the final cached `ActionResult`.

## Trust boundary

The approval ID does not grant authority. Authorization comes from the communication boundary:

- HTTP/AionUi: constant-time comparison against `AETHER_OPERATOR_TOKEN`; principal is fixed by `AETHER_OPERATOR_ID`.
- Telegram: the user ID must be explicitly listed in `TELEGRAM_ALLOWED_USER_IDS`; principal becomes `telegram:<user_id>`.

Model output, action metadata, and caller-supplied principal names cannot create authority.

## Exact binding

The action hash includes action ID, target, operation, arguments, scopes, reason, risk, reversibility, retry reason, and execution-relevant metadata. Correlation ID is excluded because it is trace-only and does not change execution semantics.

The stored proposal is re-hashed on every read. Mutation causes an integrity failure before approval or execution.

## State machine

```text
pending
  → approved → executing → consumed
  → rejected
  → expired
```

Only `approved → executing` is an execution claim. The transition is performed inside `BEGIN IMMEDIATE`, so concurrent approval clients cannot both obtain the action.

## Immutable audit

Operator decisions are inserted into `approval_records`. SQLite triggers reject update and delete operations on this table.

## Replay behavior

A consumed approval returns its cached action result and emits `approval.replay-blocked`; it never invokes the backend again. A late contradictory decision is also blocked.
