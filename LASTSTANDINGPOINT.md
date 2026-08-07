# LAST STANDING POINT - Aether OS

**Canonical date:** 2026-08-07
**Release:** MVP v0.20 - Governed Shipping + Measured Demand Operations
**State:** source-present, host-proof pending

## Canonical architecture

```text
Founder approval / release evidence
  -> validated private experiment
  -> consequence impact brief
  -> approval
  -> deployment adapter
  -> public promotion
  -> analytics and lead ledger
  -> verified demand and revenue linkage
  -> rollback / kill switch
  -> portfolio reallocation
  -> CEE strategy learning
```

## Delivered in v0.20

1. Persistent Windows service harness with heartbeat/watchdog receipts.
2. Cloudflare Tunnel ingress source harness with public probe receipts.
3. One conformed runtime body.
4. Persistent `AETHER_HOME` budget state.
5. Google TTS audition with deterministic fallback proof.
6. AionUi/Senses public health surface.
7. Aether MCP activation.
8. Founder acceptance gate.
9. MVP v0.20 release packet builder, body surface, and renderer.

## Current local proof

- `aether-runtime-body` remains fail-safe and receipt-backed.
- `aether-mvp20` can build a packet, persist it under `AETHER_HOME/runtime/releases/mvp_v0_20/`, and render this file.
- Body now exposes `/v1/body/mvp20/status` and `/v1/body/mvp20/packet`.
- Windows service and Cloudflare ingress source assets are present, receipt-backed, and ready for host proof.

## Honest boundaries

- No real public promotion was executed here.
- No verified demand or revenue linkage was proven here.
- No live rollback or kill switch was exercised here.
- Windows service and Cloudflare public proof still belong on the Founder VPS and public domain.

## Aether Senses v1 workstream

- Dee approved and froze `aether.senses.interaction.v1` on 2026-08-07. The
  canonical contract is
  `project-docs/foundations/AETHER_SENSES_V1_INTERACTION_CONTRACT.md`.
- Implementation slice 1 is source-present: provider-neutral session/turn/mode,
  consent, interruption, and capability-action contracts; a v1 runtime-profile
  guard; append-only session compatibility; and deterministic tests.
- Implementation slice 2 is source-present: rate-limited 120-second pairing,
  trusted-operator card/list and decision routes, P-256 verifier/signature
  exchange, append-only decision evidence, 30-day/7-day paired-device policy,
  one-time signed session challenges, protected `__Host-aether_device` and
  `__Host-aether_senses` cookies, memory-only CSRF, exact Origin/Fetch-Metadata
  enforcement, a 15-second client revocation heartbeat, and device revocation
  of subordinate sessions.
- The Senses shell no longer renders or reads a raw operator token and no longer
  exposes the browser session bearer token to JavaScript. Persistent WebCrypto
  storage remains best-effort with an explicit session-only pairing fallback.
- Implementation slice 3 is source-present: `persona.yaml` now owns a
  provider-neutral allowlist of delivery presets and expressive cues; a
  deterministic compiler emits only bounded director instructions; and Gemini
  TTS is available behind the common exact-text voice contract with a
  hash-only tier receipt.
- The declared Founder Alpha candidate is `gemini-3.1-flash-tts-preview` with
  voice `Aoede`, free-tier disclosure, explicit-consent and `Private text-only`
  boundaries, secret-class suppression, one-attempt quota circuit breaking,
  browser-speech/text fallback, no automatic billing upgrade, and
  `pending_founder_audition` status.
- The v1 session issuance path accepts only `GOVERNED_PIPELINE`.
  `NATIVE_AUDIO_EXPERIMENTAL` remains lab-only and cannot enter v1 evidence.
- The overall Senses v1 contract is not yet fully `IMPLEMENTED`, `WIRED`,
  `CONFORMED`, `ACTIVE`, or `FOUNDER-PROVEN`. No host capability gate changes
  merely because slices 1-3 are source-present. The Gemini adapter is not yet
  the active LiveKit worker path, `Aoede` is not Founder-auditioned or locked,
  and AionUi/Telegram presentation, browser/PWA execution, LiveKit grant
  revocation, credentialed provider execution, and Founder host evidence still
  require their own wiring and proof.

## Next Senses implementation slice

Implement one client state reducer for authentication, transport mode, turn,
consent, capability action, and external-speech privacy. Remove the generic
connected/thinking/working booleans without activating a new capability adapter.

## Next operational step

Run Windows service and Cloudflare ingress host proof on the Founder VPS, feed those receipts into Founder acceptance, then run the first governed private experiment, capture the impact brief, promote it publicly, measure demand, and feed the result back into portfolio reallocation and CEE learning.
