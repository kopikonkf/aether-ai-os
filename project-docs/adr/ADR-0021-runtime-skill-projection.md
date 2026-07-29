# ADR-0021 — Runtime Skill Projection and Invocation

## Status

Accepted for MVP v0.10.

## Decision

Runtime-specific adapters own projection and invocation. Projection artifacts are explicitly marked `projection_only` and include canonical skill ID and artifact hash. The canonical skill registry remains Aether-owned.

The first adapter supports `aether.template-v1` and structured JSON input/output. It performs no shell execution, `eval`, network calls, or filesystem side effects beyond its projection directory.

Every actual invocation records usage telemetry. The adapter validates lifecycle and artifact hash again at execution time, preventing stale route decisions from executing an archived or changed skill.

## Consequences

- A route decision is not sufficient authority; execution-time validation is mandatory.
- Approval resumption still records telemetry because telemetry lives at the runtime invocation boundary.
- Future Claude Code, Codex, OpenCode, Cursor, and other adapters implement the same profile and runtime contracts without becoming registry authority.
