# ADR-0034 — Mission Orchestrator and Expected-Value Briefs

## Status

Accepted for MVP v0.17.

## Context

Aether already had governed single actions, resumable approvals, durable memory,
internal evolution, skills, runtime routing, and fleet operations. It did not
have a durable unit of work above one action. A business idea or internal goal
could therefore become disconnected actions without a shared evidence bundle,
budget, stop conditions, or outcome ledger.

## Decision

Aether Core owns a provider-neutral `MissionOrchestrator` with two explicit
lanes:

- `internal-maintenance`
- `external-value`

An external-value mission begins as an `ExpectedValueBrief`, not an executable
plan. The brief records the problem, beneficiary, value proposition, probability
of success, upside, estimated cost, duration, revenue hypothesis, assumptions,
risk, confidence, and evidence provenance.

Expected net value is calculated deterministically:

```text
probability_success × upside_usd − estimated_cost_usd
```

An external brief requires at least two independent supporting sources. Empty
sources, missing statements, missing external references, and unresolved
contradiction evidence remain visible blockers. Evidence does not grant action
permission.

A mission plan must bind to the sole canonical Northstar through at least one
sacred-principle ID. External-value missions must also bind to a canonical
business strategy. Plans include bounded steps, dependency edges, success
criteria, budgets, and explicit stop conditions.

Only Founder/operator principals may make the terminal plan decision. Approval
of a mission plan does not approve any governed action inside the plan.

## Consequences

- Opportunities are reviewable evidence objects rather than prompts.
- Mission plans are immutable and hash-bound.
- Northstar alignment is explicit and machine-checkable.
- Contradiction and negative expected value can block execution before cost is
  incurred.
- Runtime and provider selection remain delegated to existing action/capability
  contracts.
