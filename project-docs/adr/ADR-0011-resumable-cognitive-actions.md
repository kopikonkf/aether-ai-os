# ADR-0011 — Resumable Cognitive Actions

**Status:** Accepted  
**Release:** MVP v0.5

## Decision

When cognition reaches an approval-required action, Aether persists a provider-neutral continuation checkpoint with the pending action.

The checkpoint contains:

- conversation messages at the action boundary;
- model capability and routing constraints;
- session and source identity;
- correlation ID;
- sense metadata required to deliver the eventual expression.

No model credentials or provider implementation objects are stored.

## Suspension

The cognitive gateway stops the action loop and returns a structured pending expression. It does not ask the model to pretend that the action was executed.

## Resumption

After authenticated approval:

1. the exact proposal is claimed and executed once;
2. the result is stored before being exposed as complete;
3. the result is appended to the saved messages as authoritative evidence;
4. the configured model provider continues reasoning;
5. the final expression is returned to AionUi/API or delivered to the original Telegram chat.

If no continuation exists, Aether produces a deterministic audit expression rather than fabricating a cognitive continuation.

## Replay

A duplicate approval request does not invoke either the backend or the model continuation again. The API returns the cached action result with `replayed=true`.

## Crash boundary

The local store prevents duplicate orchestration after an action is marked `executing`. A process crash after an external side effect but before finalization may leave the action in `executing`; Aether does not automatically retry it. Production runtime adapters must later add idempotency keys or reconciliation before distributed/external side effects are enabled.
