# ADR-0033 — Scheduled Fleet Operations and Incident-to-CEE Boundary

## Status

Accepted for MVP v0.16.

## Decision

Aether Gateway owns a persistent interval scheduler for four bounded jobs:
health probe, receipt renewal, budget evaluation, and incident sweep.

Job failures are recorded and classified but do not terminate the scheduler.
Receipt renewal is queue-only by default. Cost and invocation evidence is
append-only. Incident state changes are append-only transitions over a durable
incident identity.

Repeated high or critical incidents may create an `EvolutionTrigger`, but the
trigger is explicitly tagged `learning-trigger-only`. The scheduler cannot
create a candidate, mutate production, approve an action, or promote a result.

## Retry and fallback

Fleet policy publishes a maximum of three dispatch attempts, a cooldown, and the
existing invariant that the same failure fingerprint cannot be repeated without
an explicit material reason. Pending approval always stops fallback.

## Conformance attestation

Core exposes `RuntimeConformanceReceiptSigner` as a replaceable adapter contract.
Single-node v0.16 continues to route using exact local receipt fingerprints.
Distributed deployments must supply a signer/key-management adapter rather than
embedding cryptography or a key vendor into Core.

## Consequences

- Operational drift becomes durable evidence instead of transient logs.
- Scheduled observation cannot silently become autonomous authority.
- CEE receives structured failures while governance remains intact.
- Multi-node scheduling and signer implementation remain future adapters.
