# ADR-0007 — Founder Bootstrap Source Adaptation

**Status:** Accepted  
**Release:** MVP v0.3

## Source-derived requirements

The founder-supplied `Bootstrap.md` describes birth from a clean environment with no history and emphasizes a strict learning progression:

```text
empty state
  → first experience
  → patterns and concepts
  → evidence-backed belief
  → prediction
  → observed outcome
  → honest audit
```

It also explicitly rejects mass-seeding beliefs, claiming traits before testing, skipping evidence, inflating confidence, building modules without integration, measuring growth in lines of code, and confusing storage with knowledge.

## Aether architectural adaptation

The source also contains an earlier fixed implementation based on four named SQLite databases, a fixed module list, and day-number milestones. Those details are not made constitutional because Aether is memory agnostic and must evolve its implementation without losing its learning discipline.

Aether therefore preserves the source's epistemic sequence and prohibitions while replacing implementation-specific assumptions with machine-verifiable gates:

- `src/aether/dna/north_star.yaml` remains the sole directional authority.
- `Genome.md` remains constitutional identity material.
- A third-party memory provider is not required for first boot.
- A conversation cannot be promoted directly into a belief.
- Beliefs require provenance and evidence.
- Progression is evidence-gated rather than calendar-gated.
- Storage schemas are replaceable implementation details.

## Executable artifact

The normalized policy is packaged at:

```text
aether/bootstrap/bootstrap.yaml
```

It is verified by `aether.bootstrap.validate_bootstrap_policy` and:

```bash
python aether_cli.py bootstrap-check
```
