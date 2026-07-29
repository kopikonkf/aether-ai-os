# ADR-0018 — Aether-Owned Skill Factory

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

Aether skills are canonical runtime-neutral manifests owned by Aether Core. Runtime-specific skill files are projections created by adapters and never become the source of truth.

A skill candidate must contain:

- name, version, summary, and instructions;
- a capability-oriented usage contract;
- input/output schemas, declared side effects, and runtime requirements;
- trigger provenance and evidence IDs;
- observed and successful workflow counts;
- generator identity;
- deterministic and held-out benchmark commands;
- an exact canonical artifact hash.

Candidates may originate from repeated successful workflows, explicit capability gaps, or revisions of an existing Aether skill.

## Activation gate

Activation requires:

1. candidate constraints pass;
2. evidence requirements pass;
3. deterministic candidate checks pass;
4. held-out candidate checks exist and pass;
5. candidate score meets the minimum;
6. improvement over baseline is positive;
7. regressions are zero;
8. a trusted Founder/operator records an explicit reason;
9. a runtime installer adapter returns a projection receipt.

The model, generator, curator, or CEE cannot self-authorize activation.

## Consequences

- One Aether skill can be projected into many runtimes.
- Runtime migration does not destroy skill identity or usage history.
- Provider/runtime-specific packaging remains outside Core.
- Skill intelligence can evolve while governance remains stable.
