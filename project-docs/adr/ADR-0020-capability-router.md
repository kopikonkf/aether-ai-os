# ADR-0020 — Capability Router

## Status

Accepted for MVP v0.10.

## Decision

Aether Core receives `CapabilityRequirement` objects and selects active skills by exact capability, schema validity, lifecycle, runtime feature compatibility, and side-effect compatibility. Core treats runtime routing keys as opaque tokens and never branches on runtime product names.

The model-visible action is `capability.route`. Direct `skill.execute` capability is hidden from model tool declarations. After selection, the router creates the exact `ActionProposal` and sends it through the existing Governed Action Path.

## Consequences

- Runtime replacement does not modify Core routing logic.
- Archived and superseded skills cannot be silently selected.
- Governance remains the only execution authority.
- Fallback is bounded and auditable.
- No-match and exhausted fallback paths produce durable fingerprints.
