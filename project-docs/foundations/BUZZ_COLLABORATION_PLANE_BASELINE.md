# Buzz Collaboration Plane Baseline

Status: APPROVED FUTURE MINI-PROJECT; DEFERRED UNTIL AFTER AIONUI
Date: 2026-07-29

## Position

- Aether: Mind, governance, mission orchestration, synthesis, memory authority.
- AionUi: private Founder cockpit and infrastructure control plane.
- Buzz: optional sovereign human-agent collaboration plane.
- Runtime bodies: Codex, Claude Code, Goose, OpenCode, and future workers.

Buzz never becomes Aether's identity, governance authority, or canonical memory.

## Preparation before implementation

1. Pin an exact Buzz release or commit after AionUi integration; never target floating `main`.
2. Record upstream commit, container image digests, database schema version, and feature conformance.
3. Deploy Buzz on an isolated Linux host/container boundary, not inside Aether Mind process.
4. Create separate cryptographic identities for Aether, Founder, and every worker.
5. Keep private keys out of model context and worker environments.
6. Define relay/channel allowlists and event-kind allowlists.
7. Map Aether mission/task/result/approval IDs to signed Buzz events.
8. Preserve event ID, signer pubkey, timestamp, payload hash, and artifact hash as evidence.
9. Do not auto-ingest Buzz conversations into canonical memory.
10. Treat huddle audio as a later Sense adapter after text/task conformance.

## Mini-project conformance ladder

1. Read-only relay health and event subscription.
2. Aether identity joins one private room.
3. Receive one Founder-authored signed message.
4. Publish one signed Aether status event.
5. Dispatch one bounded task to one worker.
6. Receive progress and final result receipts.
7. Verify artifact hash and signer identity.
8. Cancel/timeout one task safely.
9. Restart and resume subscriptions without duplicate execution.
10. Prove Buzz outage cannot stop Aether Core/Gateway.

## Governance boundary

A Buzz reaction, message, or workflow approval is not automatically an Aether approval. Translation is allowed only for a registered Founder signing key, exact action hash, correct channel scope, valid expiry, and exact-once consumption.

## Initial schemas

- `buzz_task_envelope.schema.json`
- `buzz_result_receipt.schema.json`

These schemas are design contracts only until a `CollaborationPlanePort` and conformance adapter are wired.
