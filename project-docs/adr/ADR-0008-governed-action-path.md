# ADR-0008 — Governed Action Path

**Status:** Accepted  
**Release:** MVP v0.4

## Decision

All model-requested actions must be represented as provider-neutral `ActionProposal` objects and executed through `GovernedActionPath`.

No sense adapter, model provider, or response parser may call a tool or runtime directly.

## Required sequence

```text
action.proposed
  → governance.approved | governance.rejected
  → action.execution.requested
  → backend execution
  → action.completed | action.failed
```

Runtime delegation additionally emits `runtime.command.requested` and `runtime.result.received`.

## Governance

The policy is default-deny. MVP auto-approval is limited to:

- reversible, low-risk `tool/read` with `read` scope;
- reversible, low-risk `runtime/echo` with `execute` scope.

Other operations require an `ActionApproval` supplied through a trusted channel. Approval metadata inside a model response is ignored.

## Failure invariant

Each failed action produces a durable fingerprint based on target, operation, normalized arguments, scopes, error type, and error text.

Before execution, Aether checks for unresolved identical failures. A retry is blocked unless `retry_reason` explicitly states why conditions materially changed. This operationalizes the constitutional rule that Aether must not repeat the same mistake without an explicit reason.

## Cognition continuation

Action output is returned to the cognitive gateway as authoritative execution evidence. The model receives the governed result and must produce a final expression without inventing execution.

## Removed path

The legacy Core `RuntimeManager` and `[TOOL ...]` parser integration were removed. Core no longer imports `aether-tools`.
