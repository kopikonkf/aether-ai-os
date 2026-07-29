# ADR-0032 — Native AionUi Runtime Console

## Status

Accepted for MVP v0.16.

## Decision

Aether provides two operator surfaces:

1. A packaged browser console served by Aether Gateway.
2. A native AionUi v2 integration pack implemented as React renderer code,
   preload IPC exposure, and an Electron main-process service.

The native renderer never receives the operator token. The main process owns the
secret and performs authenticated requests to Aether Gateway. AionUi remains an
operator shell; it does not own scheduling, incident classification, budgets,
conformance, or action approval semantics.

## Rationale

A direct renderer-to-Gateway token would broaden the trusted computing base and
make token leakage through DOM, developer tools, or renderer compromise more
likely. IPC preserves the existing desktop process boundary and keeps policy in
Aether.

## Installation boundary

The release contains a non-destructive installer that adds new files to an
AionUi v2 checkout. Shared bootstrap, preload, router, and sidebar files are not
rewritten automatically. Exact snippets are supplied because those files evolve
upstream and are authority-sensitive.

## Consequences

- Gateway can operate without AionUi.
- Closing AionUi does not stop scheduled fleet jobs.
- Native AionUi requires a short wiring step and an upstream build.
- The packaged WebUI remains an immediate executable fallback.
