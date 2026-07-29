# ADR-0023 — First Coding Runtime Body

**Status:** Accepted  
**Date:** 2026-07-28

## Decision

The first body is `LocalStructuredCodingRuntimeAdapter`, a deterministic reference adapter for bounded source edits and verification.

It accepts structured edits rather than arbitrary shell instructions. Existing files require an expected SHA-256. Paths must be relative, remain within the bound workspace and runtime allowlist, and satisfy file/byte limits.

## Execution

1. Validate workspace ID, session, writable status, and allowed root.
2. Validate paths, expected hashes, file count, and byte count.
3. Create an external backup lineage.
4. Apply edits atomically.
5. Emit structured progress and artifact events.
6. Run allowlisted Python module verification without a shell.
7. Keep verified changes or roll back all edits on failure.
8. Return bounded diffs, hashes, sizes, verification receipts, and telemetry.

## Security boundary

The adapter provides no arbitrary shell, `eval`, network action, package installation, or free-form code-generation authority. Write execution remains subject to the Governed Action Path and Trusted Approval Inbox.

## Rationale

A deterministic body validates the SDK and governance boundary before introducing a live coding-agent CLI. External runtimes can later generate or execute richer plans behind the same contract, without becoming Aether's mind.
