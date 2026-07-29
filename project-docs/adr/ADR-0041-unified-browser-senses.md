# ADR-0041 — Unified Browser Senses

**Status:** Accepted

## Decision

Implement browser microphone, speaker, camera, and text as Gateway adapters. Use LiveKit as an optional realtime transport and speech pipeline. Delegate every completed cognitive turn to Aether Gateway. Preserve provider-neutral contracts and append-only session/media/turn receipts in Core.

## Consequences

- VPS requires no physical microphone, speaker, or camera.
- media services remain replaceable;
- missing LiveKit is non-fatal;
- raw media is excluded from event and text-memory logs;
- camera cognition is explicit or bounded opt-in;
- real voice readiness requires deployment credentials and SDKs.
