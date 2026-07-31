# ADR-0047 — Action Preflight Before Approval and Failed-Approval Stop

**Status:** Accepted  
**Date:** 2026-07-29  
**Applies to:** Aether v0.19.2 Founder Alpha consolidated build

## Context

A Founder asked Aether through Telegram to create a file at `D:\`. The default tool policy permits writes only under `AETHER_HOME`. The previous action path performed governance and consumed trusted approval before the tool adapter validated the target path. Execution then failed. The cognition continuation could propose the same action again, creating a new approval request.

The approval ledger behaved exactly-once, but the overall user experience was incorrect:

1. approval was requested for an action that could never pass capability policy;
2. approval was consumed before the deterministic failure was known;
3. the failed action could be proposed repeatedly without a new explicit retry reason.

## Decision

Aether performs a side-effect-free action preflight before governance approval for tool actions.

```text
proposal
→ tool schema and policy preflight
→ unresolved-identical-failure gate
→ governance decision
→ trusted approval when needed
→ execution
→ receipt
```

Additional decisions:

- A preflight failure emits `action.preflight.failed` and creates no pending approval.
- A failed approved action returns its backend error directly to the requesting sense.
- The model is not resumed with tools after a failed approved action; automatic retry is disabled.
- An unresolved identical execution failure blocks a repeat unless the next proposal carries an explicit `retry_reason`.
- Native tool schemas are authoritative. The canonical write arguments are `path` and `content`; legacy `_body` remains accepted by `WriteTool` for compatibility.
- File policy remains deny-by-default outside configured roots. Trusted approval does not override capability policy.

## Consequences

Positive:

- impossible actions do not waste approval attention;
- exact-once approval semantics remain intact;
- repeated-failure constitutional rule becomes executable;
- Telegram displays the actual backend error;
- tool permissions remain separate from human approval.

Trade-offs:

- adapters must implement deterministic validation without side effects;
- dynamic failures can still occur after approval and execution starts;
- an intentionally retried failed action must include an explicit reason.

## Verification

The consolidated test slice verifies:

- impossible write path fails before approval creation;
- registry validation is side-effect-free;
- native write `content` argument succeeds;
- an identical unresolved failure is blocked before a second approval;
- failed approved action does not re-enter the model/tool loop.
