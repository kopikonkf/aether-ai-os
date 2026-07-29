# ADR-0029 — OpenCode Driver and Credential Isolation

## Status

Accepted for MVP v0.14.

## Context

Aether requires a provider-selectable coding body that is not structurally tied to one subscription vendor. OpenCode provides the desired runtime surface, but its credential must not enter Aether source, argv, telemetry, or release artifacts.

## Decision

Implement `opencode-cli` as a Gateway translator into `aether.coding-jsonl.v1`.

The operator configures only a credential-file path. The translator creates a restricted, in-memory OpenCode configuration using file substitution. The child process receives a sanitized environment and a disposable home/workspace. Aether snapshots the disposable workspace and emits complete-text patch evidence; it never trusts OpenCode's success claim or diff.

The translator redacts the secret value from normalized vendor metadata before the parent persists the stream transcript.

## Consequences

- A key value is absent from command-line arguments and durable Aether configuration.
- The key file remains an operator-managed deployment secret.
- OpenCode can select a different provider/model without Core changes.
- A changed model or credential reference invalidates the existing conformance receipt.
- Provider availability, quotas, privacy terms, and model IDs remain deployment-time concerns.
