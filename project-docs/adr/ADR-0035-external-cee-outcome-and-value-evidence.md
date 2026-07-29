# ADR-0035 — External CEE Outcome and Value-Evidence Boundary

## Status

Accepted for MVP v0.17.

## Decision

Mission execution is resumable and bounded. Each run executes at most the
configured number of steps, persists a continuation checkpoint, and stops when
it reaches an approval boundary, budget boundary, terminal failure, or explicit
operator pause/cancel.

Every step uses the existing Governed Action Path. A pending action approval is
stored as an exact checkpoint. Resuming the mission reads the consumed approval
result; it does not propose or execute the same action a second time.

Mission value uses three separate evidence classes:

```text
claimed  → hypothesis or estimate
realized → external evidence that value/revenue occurred
verified → realized evidence reviewed by a trusted Founder/operator
```

Realized and verified value require an external reference. Verified evidence
must reference realized evidence from the same mission and cannot exceed its
amount. Claimed value is never reported as revenue.

Outcome finalization requires a trusted principal, a terminal mission execution
state, and is single-use. Mission lessons may be written to canonical memory as
reflection records marked `knowledge_candidate`; they do not become knowledge,
belief, DNA, or Northstar automatically.

Mission failure may create an internal evolution trigger with
`authority=learning-trigger-only`. It does not create a code candidate or mutate
production automatically.

## Consequences

- Revenue reporting has an auditable evidence chain.
- A model cannot declare its own mission successful or verify its own revenue.
- Approval, pause, restart, and crash recovery do not duplicate side effects.
- External CEE can learn from missions without acquiring autonomous mutation or
  financial authority.
