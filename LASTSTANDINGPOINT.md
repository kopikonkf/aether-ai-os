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
- The v1 session issuance path accepts only `GOVERNED_PIPELINE`.
  `NATIVE_AUDIO_EXPERIMENTAL` remains lab-only and cannot enter v1 evidence.
- The overall Senses v1 contract is not yet fully `IMPLEMENTED`, `WIRED`,
  `CONFORMED`, `ACTIVE`, or `FOUNDER-PROVEN`. No host capability gate changes
  merely because slice 1 is source-present.

## Next Senses implementation slice

Replace the raw operator-token form with the approved pairing/device bootstrap
and protected same-origin session-cookie boundary. This is source work and does
not replace the outstanding Windows service and Cloudflare host proof.

## Next operational step

Run Windows service and Cloudflare ingress host proof on the Founder VPS, feed those receipts into Founder acceptance, then run the first governed private experiment, capture the impact brief, promote it publicly, measure demand, and feed the result back into portfolio reallocation and CEE learning.
