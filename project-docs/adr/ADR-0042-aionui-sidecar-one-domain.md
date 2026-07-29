# ADR-0042 — AionUi Sidecar and One-Domain Deployment

**Status:** Accepted

## Decision

Keep Aether Gateway, LiveKit worker, AionUi WebUI, runtime workers, and reverse proxy as separate supervised processes. Present them through one HTTPS domain. Add a native AionUi `/senses` page and a guarded installer, but do not move Aether identity, cognition, memory, or governance into AionUi.

## Consequences

- one browser URL for the Founder;
- independent replacement and restart of UI, media, and runtime components;
- Caddy routes only browser-sense paths directly to Aether;
- systemd and Docker Compose deployment paths are provided;
- upstream AionUi build compatibility must be verified at deployment time.
