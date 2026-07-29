# ADR-0031 — Runtime Operations Console

## Status

Accepted — MVP v0.15

## Context

A multi-driver fleet needs one Aether-owned operational view. Vendor dashboards cannot represent Aether governance, exact conformance, cross-driver reliability, pending receipt renewal, or routing eligibility.

## Decision

Add an operations snapshot contract and Gateway console that combines:

- driver discovery and authentication readiness;
- exact conformance state and expiry;
- routing eligibility;
- provider/model configuration;
- invocation-derived reliability;
- quota/rate-limit/authentication classification;
- renewal-window state.

Expose the console through authenticated HTTP and CLI. Allow operators to refresh evidence and renew receipts that are already due. Do not let console state approve actions or mutate workspace authority.

## Consequences

- Operations remain visible even when all vendor CLIs are unavailable.
- Quota and reliability can adjust routing priority but cannot bypass governance.
- v0.15 is an API/CLI console; native AionUi rendering and scheduled fleet jobs are deferred.
- Quota classification is evidence derived from vendor streams, errors, and exit behavior; it is not billing authority.
