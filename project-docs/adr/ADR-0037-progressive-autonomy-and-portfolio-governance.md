# ADR-0037 — Progressive Autonomy and Portfolio Governance

## Status

Accepted for MVP v0.18.

## Context

A safety model that requires approval for every observation or reversible experiment would starve Aether of learning. Unlimited external authority would expose humans and Aether to irreversible harm, financial liability, identity misuse, and corrupted self-evolution.

## Decision

Adopt progressive autonomy:

```text
observe                 autonomous
synthesize              autonomous
sandbox experiment      budgeted mandate
bounded external        mission mandate
high consequence        explicit action approval
```

Governance scales with consequence, not with the number of internal steps.

Portfolio selection is separate from candidate synthesis. A model may synthesize and score candidates but cannot select itself. Trusted selection may allocate a bounded experiment budget. A reusable mandate cannot grant high-consequence authority.

Portfolio policy enforces:

- independent evidence;
- contradiction blocking;
- total budget;
- high-risk count;
- category concentration;
- exploration reserve.

## Consequences

Aether can explore and learn aggressively while preserving human rights, assets, identity, and irreversible commitments. Autonomy can grow through evidence and reliability rather than being permanently denied or universally granted.
