# ADR-0038 — Live Web Source Conformance and Evidence Freshness

## Status

Accepted for MVP v0.19.

## Context

v0.18 introduced a source mesh and immutable opportunity evidence but did not prove a live source path. Package detection alone cannot establish that DNS, credentials, domain policy, crawler runtime, and extraction actually work together.

## Decision

A live source is represented by a versioned Core configuration and becomes eligible only after Gateway issues an exact conformance receipt bound to:

- configuration hash;
- adapter manifest hash;
- adapter version;
- bounded live canary result;
- expiration.

Enabled HTTP(S) conformance requires a successful, non-empty canary acquisition. Manifest or configuration change makes the receipt stale. Credentials remain opaque handles.

Freshness is an append-only assessment of snapshots. Adaptive discovery may propose new source domains but cannot activate them.

## Consequences

- “Installed” is no longer confused with “live.”
- Offline deployments degrade honestly without blocking Core.
- Historical evidence remains auditable.
- Source expansion remains autonomous at proposal level and governed at activation level.
