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
- Implementation slice 4 is source-present: the Senses shell now derives
  authentication/session, transport mode, turn, camera/screen consent,
  capability-action, and external-speech privacy presentation from one
  deterministic client reducer. Invalid transitions fail closed, stale async
  events are bound to a session epoch, and the shell no longer uses generic
  connected/thinking/working presentation booleans.
- The six axes are visible independently. `Private text-only` persists across
  turn boundaries and suppresses browser/external speech without disabling
  Gateway text cognition. External-provider consent cannot become granted
  without an authoritative consent receipt, and a capability cannot become
  `SUCCEEDED` without an authoritative execution receipt.
- Camera enablement in the shell is now local preview only and no longer
  publishes continuous camera video to LiveKit. This safety correction does
  not claim bounded-vision conformance: server-side consent leases, keyframe
  validation, raw-frame deletion, and crash sweeping remain pending.
- The v1 session issuance path accepts only `GOVERNED_PIPELINE`.
  `NATIVE_AUDIO_EXPERIMENTAL` remains lab-only and cannot enter v1 evidence.
- The overall Senses v1 contract is not yet fully `IMPLEMENTED`, `WIRED`,
  `CONFORMED`, `ACTIVE`, or `FOUNDER-PROVEN`. No host capability gate changes
  merely because slices 1-4 are source-present. The Gemini adapter is not yet
  the active LiveKit worker path, `Aoede` is not Founder-auditioned or locked,
  and AionUi/Telegram presentation, browser/PWA execution, LiveKit grant
  revocation, credentialed provider execution, and Founder host evidence still
  require their own wiring and proof.

## Next Senses implementation slice

Implement cancellable turn generations, stop LiveKit/browser/provider audio,
discard late audio/results, and reconcile network-ambiguous turns by stable
turn/correlation ID without automatically replaying cognition or external
actions. Do not treat speech interruption as capability-action cancellation.

## Next operational step

Run Windows service and Cloudflare ingress host proof on the Founder VPS, feed those receipts into Founder acceptance, then run the first governed private experiment, capture the impact brief, promote it publicly, measure demand, and feed the result back into portfolio reallocation and CEE learning.

## Cloudflare ingress PR #34 (round-4, 2026-08-07)

- **Head:** `aa91939` (branch `agent/founder-auth-0053`), rebased onto exact main
  `b57403395f7838972575b7fb7149d3d0e457dc3e` (incl. #36 bootstrap + #37 voice +
  #38 Senses client-state slice-4). `mergeable_state=clean`, `mergeable=true`,
  synthetic-merge commit `9594ef3`.
- **4 round-3-then-4 review blockers from ChatGPT all addressed:**
  1. Rebase to exact main (done, no conflicts).
  2. Boundary proof uses the ACTUAL production Caddyfile
     `deploy/windows/Caddyfile`: render with both `:8000`/`:25808` upstreams
     re-pointed at the echo server so every handler exercises the template's own
     `header_up -Authorization`. No bespoke test Caddyfile. Echo/PROOF route is
     proof-only; production Caddyfile keeps no public echo endpoint.
  3. One complete CaddyBasic receipt in a single real-probe invocation
     (correct + wrong creds + echo via stdin): asserts
     `unauthenticated_all_denied=true`, `authenticated_all_ok=true`,
     `invalid_credentials_all_denied=true`, `header_strip_observed=true`,
     `authorization_forwarded_to_upstream=false`, `secret_values_exposed=false`.
  4. Hash staging conforms ADR-0053: README stages bcrypt to a transient temp
     `.txt` (never `.env`); installer `Assert-ProtectedAcl` on hash input (exact
     SYSTEM+Administrators, inheritance-protected) before reading, then
     `Remove-Item` it after `founder-auth.caddy` is safely written. Only the
     protected canonical fragment persists.
  5. CI: `Real ingress boundary proof` (pwsh 7.4.6 + Caddy v2.11.3 linux, env
     `AETHER_INGRESS_INTEGRATION=1`) = `6 passed`, NOT skipped. Run
     `31173898737` (synthetic merge on `aa91939`) = success. Mergeable clean.
  6. VPS/DNS/tunnel/Access/Cloudflare untouched.
- **Local:** 27/27 cloudflare tests pass (assets/probe_modes/probe_behavior/
  integration) on Windows PS 5.1 + Caddy 2.11.3. Full `tests/` = 50 pass with only
  pre-existing `test_state_snapshot` canonical.sqlite3 Windows lock failure
  (unrelated; ok on ubuntu CI).
- **Report posted:** https://github.com/kopikonkf/aether-ai-os/pull/34#issuecomment-5216460430
- **Waiting:** ChatGPT to merge PR #34. After merge: stage exact main -> generate
  bcrypt hash interactive (temp `.txt`, `icacls` to SYSTEM+Admins; installer
  removes it) -> `aether_migration_<sha>.ps1` cutover -> validate
  `PASS_READY_FOR_PRODUCTION_SERVICE_INSTALL` -> production install (AetherService
  + Watchdog, no sense-worker) -> ACL -> local auth proof (production Caddyfile +
  proof echo) -> reuse tunnel `8f53133` + DNS cutover `:8080` -> public proof +
  recovery receipts CONFORMED.
