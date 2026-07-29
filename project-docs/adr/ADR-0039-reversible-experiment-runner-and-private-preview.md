# ADR-0039 — Reversible Experiment Runner and Private Preview

## Status

Accepted for MVP v0.19.

## Context

Progressive autonomy requires Aether to test selected opportunities without asking for every reversible step, while preserving authority boundaries for external consequences.

## Decision

Introduce a mandate-bound runner with five fixed operations: artifact write, artifact verification, private preview, demand-measurement preparation, and external-action review.

The runner operates only in disposable workspaces and has no arbitrary shell, arbitrary network, or production-write capability. Plans and runs enforce cost, monotonic duration, bytes, and unique file-count budgets. Private preview tokens are returned once and stored only as hashes.

Synthetic, measured, and verified demand are distinct evidence classes. An external-action step stops execution and creates an operator review.

## Consequences

- Aether can build and validate private prototypes autonomously inside a mandate.
- Public shipping and other consequences remain governed.
- Experiment results are reproducible and evidence-backed.
- The fixed operation set is intentionally narrower than a general runtime; additional operations require explicit adapter and policy decisions.
