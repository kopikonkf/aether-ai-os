# ADR-0019 — Skill Curator Lifecycle

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

Skill lifecycle is append-only and telemetry-informed:

```text
active → stale → archived
active/stale → superseded
archived → reactivation only after fresh benchmark and trusted decision
```

Curator telemetry may recommend or automatically mark `stale` under bounded policy. It may not archive, reactivate, delete, modify DNA, promote beliefs, or activate a revision.

Archive retains:

- the canonical registry record;
- the runtime projection artifact;
- decision and benchmark records;
- usage telemetry;
- lifecycle events;
- provenance and prior-skill lineage.

A revision is a new candidate bound to `prior_skill_id`. Activating it appends a new registry record and marks the earlier record `superseded`; no existing artifact is rewritten.

## Rationale

Staleness is an operational observation, not evidence that knowledge or identity is wrong. Deletion would destroy provenance and prevent future forensic review. Trusted terminal lifecycle decisions keep the CEE and curator from silently changing production capabilities.
