# ADR-0028 — Multi-Driver Conformance Receipts

## Status

Accepted for MVP v0.14.

## Context

CLI discovery alone is insufficient for live routing. A binary may change after installation, a configuration may select another provider/model, or a driver translator may no longer match the executable version. Runtime health must be evidence-bound rather than inferred from a command name.

## Decision

Aether stores append-only `RuntimeConformanceReceipt` records outside Core execution logic. A receipt binds the exact manifest fingerprint, executable path and SHA-256, version, protocol, provider/model, non-secret configuration hash, suite hash, operator identity, issue time, expiry, and individual checks.

A `ConformanceGatedRuntimeAdapter` revalidates the executable and configuration reference before health reporting and execution. Missing, failed, expired, or stale receipts make the adapter ineligible for live routing.

The receipt grants only routing eligibility. It does not approve tasks, grant workspace authority, or bypass independent verification.

## Consequences

- Binary replacement requires reconformance.
- Provider/model or credential-reference changes require reconformance.
- Planned drivers cannot be made live by writing a receipt.
- Conformance history remains auditable because the SQLite ledger rejects update and delete.
- MVP receipts use content fingerprints and trusted operator identity; external cryptographic signatures remain future work.
