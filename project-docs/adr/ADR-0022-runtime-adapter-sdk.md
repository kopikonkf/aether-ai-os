# ADR-0022 — Runtime Adapter SDK

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

Aether defines a product-neutral coding runtime contract in Core and implements discovery, health inspection, workspace binding, telemetry, and concrete adapters in Gateway.

A runtime descriptor exposes an opaque routing key, adapter ID, operations, capabilities, features, health, priority, and metadata. Core may compare capability and compatibility fields but may not branch on vendor or product names.

The model-visible route is `coding.delegate`. The concrete body operation `coding.task.execute` is hidden from model tool declarations and may only be constructed by the coding runtime router after workspace and runtime checks.

## Workspace authority

A model does not submit a raw filesystem root as authority. A trusted operator first binds an opaque `workspace_id` to:

- one canonical root;
- one session;
- an allowed relative-path set;
- writable or read-only status.

Bindings are immutable. The concrete runtime independently rechecks its configured allowed roots at execution time, including after delayed approval.

## Conformance

Adapter registration fails before discovery when IDs, routing key, required operation, capabilities, or protocol methods are inconsistent.

## Consequences

Claude Code, Codex, OpenCode, Cursor, and future bodies can be added without changing Aether Core. Each adapter remains transport/execution machinery rather than mind, identity, governance, or canonical registry.

## Post-approval fallback

The approved action binds an ordered candidate list to one exact action hash. A private dispatch adapter may try those candidates up to the policy limit after approval. It cannot add a runtime that was not included in the approved proposal.
