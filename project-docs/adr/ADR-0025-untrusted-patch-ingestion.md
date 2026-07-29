# ADR-0025 — Untrusted Patch Ingestion and Independent Verification

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

A patch emitted by an external runtime is untrusted. It may only modify a bounded staging copy. Aether validates path and hash integrity, executes independent allowlisted verification, rechecks production hashes, and applies verified bytes atomically. A failed verification never changes production. A failed production apply triggers rollback for every already-applied artifact.

## Consequences

- Runtime claims and diffs are evidence, not authority.
- Existing production files require an exact before-hash.
- External progress can be displayed live without granting execution authority.
- A malicious external process is not fully contained by v0.12 because isolation is process-policy and staging-based, not kernel-enforced. Stronger container or microVM isolation remains future work.
