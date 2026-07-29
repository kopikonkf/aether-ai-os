# ADR-0048 — Founder-Interactive Approval UX with Authoritative Completion Receipts

**Status:** Accepted for `v0.19.2-founder-alpha-frozen.1`  
**Scope:** Telegram Founder interaction; governed action completion rendering

## Context

The exact-once approval ledger in consolidated.1 worked, but the human interaction was unnecessarily mechanical:

```text
/approve <approval_id> <reason>
```

Even when a Telegram chat contained exactly one pending action, the Founder had to copy an identifier and invent a reason. After successful execution, cognition was invoked a second time to describe the result. That model-generated description could differ from the payload actually written to disk and could emit stale text such as `Waiting for operator approval`.

## Decision

### 1. Keep exact action binding

Every side-effect approval remains bound to:

- exact action hash;
- exact approval ID;
- authenticated principal;
- channel;
- expiry;
- exact-once consumption;
- durable execution receipt.

Bot-to-bot and API integrations continue to use explicit identifiers and reasons.

### 2. Add a Founder-friendly Telegram projection

For a trusted Telegram operator:

- `/yes` approves the only pending action in the current chat;
- `/no` rejects the only pending action in the current chat;
- `/approve` and `/reject` without arguments behave the same way;
- `/approve <approval_id>` and `/reject <approval_id>` use an auditable default reason;
- when multiple actions are pending, an explicit approval ID is still required;
- an optional human reason may always be appended.

This is a presentation shortcut. It does not weaken the underlying approval contract.

### 3. Stop model-generated post-approval claims

Successful approved actions are rendered deterministically from the authoritative `ActionResult`. The model is not called again merely to announce completion.

For writes, the receipt includes:

- action ID;
- operation;
- full resolved path;
- byte count;
- created/overwritten disposition;
- SHA-256 of the bytes written;
- exact-once approval ID.

The Telegram response no longer reprints a model-generated approximation of file content. Exact content verification is performed through a subsequent read action when needed.

### 4. Auto-approve bounded observation tools

The following side-effect-free capabilities do not interrupt the Founder:

- `read`;
- `glob`;
- `grep`;

Writes, edits, shell execution, memory mutation, high-risk operations, irreversible operations, and external side effects remain governed according to policy.

## Consequences

- Human interaction is materially faster.
- Exact-once and action-hash security remain intact.
- Telegram completion messages cannot drift from disk state.
- Bot/API callers retain explicit machine-safe contracts.
- Multiple simultaneous pending actions remain fail-closed against ambiguous `/yes` input.
