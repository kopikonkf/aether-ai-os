# ADR-0024 — External Coding Runtime Protocol

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

External coding bodies integrate through a product-neutral, line-delimited JSON protocol named `aether.coding-jsonl.v1`. Runtime discovery occurs through a separate handshake that reports version, capabilities, features, operations, and limits. Core owns the contracts and policy; Gateway owns process transport and vendor translation.

## Consequences

- Aether can replace coding CLIs without Core changes.
- Runtime product names never become branches in Core.
- Progress and artifact output are normalized into canonical Aether contracts.
- Runtime credentials and command configuration remain outside Core.
- The reference runtime proves protocol conformance but is not treated as a production AI coding agent.
