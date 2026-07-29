# ADR-0030 — Gemini CLI and Claude Code Driver Pack

## Status

Accepted — MVP v0.15

## Context

Aether required two additional generative coding bodies without adding vendor-specific concepts to Core. Gemini CLI exposes a headless streaming surface, while Claude Code exposes non-interactive JSONL output and explicit tool controls. Both can generate workspace edits, but neither can be trusted with production authority.

## Decision

Implement separate Gateway translators for Gemini CLI and Claude Code. Each translator:

1. discovers its CLI and version without shell execution;
2. reports authentication readiness through references, never secret values;
3. runs in a disposable workspace copied from Aether staging;
4. normalizes vendor events into `aether.coding-jsonl.v1`;
5. emits generated file bytes as untrusted patch evidence;
6. relies on Aether for held-out verification and production mutation.

Gemini receives an isolated home and policy denying shell/network tools. Claude receives an isolated config copy and a bounded file-tool allowlist while Bash, web, notebook, and agent delegation tools are denied.

## Consequences

- Aether Core remains vendor-neutral.
- Both CLIs can be absent without preventing boot.
- Authentication changes invalidate exact conformance state through configuration-reference metadata.
- Vendor process sandboxing remains process/filesystem-level, not a kernel-enforced security boundary.
- Real CLI compatibility must be verified in deployment through conformance receipts.
