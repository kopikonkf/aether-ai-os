# ADR-0003 — CEE Authority, Bootstrap, and Factories

**Status:** Accepted architecture; optimizer contract defined, execution engine not enabled  
**Decision date:** 2026-07-27

## Source reading

The current DNA establishes:

- evidence over confidence;
- provenance over accumulation;
- falsifiability;
- belief lifecycle and regular audits;
- Genome before memory;
- no unexplained repeated mistakes;
- chosen continuous improvement;
- generational value creation as North Star.

## Authority correction

`src/aether/dna/north_star.yaml` is the sole North Star authority. The former documentation-level duplicate has been deleted from the executable core so no derived configuration can compete with DNA.

## Bootstrap is not identity

Bootstrap is the deterministic rebirth process:

1. verify DNA integrity;
2. load the authority bundle;
3. restore append-only state and governed knowledge;
4. rebuild provider indexes;
5. recover active objectives and budgets;
6. enter conservative mode when an invariant fails.

Bootstrap is governed machinery derived from DNA, not frozen identity itself.

## Factory is not identity

Factories convert constitutional direction into bounded work. They are evolvable operational systems:

- **Objective Factory:** North Star → objective → project → task;
- **Experiment Factory:** uncertainty → hypothesis → test → evidence;
- **Capability Factory:** failure pattern → skill proposal → verification → promotion;
- **Business Factory:** opportunity → market evidence → unit economics → bounded execution → value outcome.

Factories may change as evidence improves. Therefore they should not live inside immutable DNA.

## CEE dual-lane model

### Internal Evolution Lane

Improves Aether's reliability, architecture, skills, tests, and operating capacity.

### External Value Lane

Discovers and validates real opportunities, produces bounded deliverables, and measures revenue or economic value.

Both lanes use the same loop:

`observe → fingerprint → recall prior incidents → propose bounded experiment → govern → execute in isolation → verify → promote or rollback → record durable learning`

## Repeated-mistake invariant

Before executing an action, CEE must query failure fingerprints. A matching prior failure requires one of:

- a verified prevention is active;
- the new attempt materially differs and states why;
- governance records an explicit exception.

Otherwise execution is blocked.

## Autonomous-improvement invariant

Aether may generate improvement proposals without a human prompt. It may automatically execute only low-risk, reversible, budgeted experiments. Identity changes, financial commitments, credential changes, external high-risk effects, and production self-modification remain governance-gated.

## "Idle is failure" correction

The useful intent is retained without forcing wasteful activity:

> When no user task is active and an authorized resource budget exists, Aether should select the highest-value bounded objective or experiment. When no safe and evidence-backed work exists, waiting and gathering evidence is valid.

Unbounded activity is not improvement.
