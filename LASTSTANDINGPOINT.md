# LAST STANDING POINT - Aether OS

**Canonical date:** 2026-08-08
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
  publishes continuous camera video to LiveKit. That slice-4 safety correction
  preceded the server-side consent, keyframe validation, deletion, and sweeping
  work now recorded under slice 6 below.
- Implementation slice 5 is source-present: every browser and LiveKit voice
  generation has a stable `turn_id`, `correlation_id`, and monotonic generation;
  an append-only SQLite claim ledger prevents the same ID from authorizing
  cognition twice; and explicit retries use a new turn ID linked by
  `retry_of_turn_id`.
- `Stop Aether`, Escape, user barge-in, competing typed input, disconnect, and
  Private text-only invalidate the prior generation. Available browser speech,
  recognition, remote LiveKit audio elements/tracks, AgentSession playout, and
  provider synthesis are stopped through their owning surfaces. The worker
  publishes bounded turn-state metadata only—never transcript or response text—
  so the browser can bind Stop to the exact worker generation.
- Browser and worker callbacks discard any result whose turn, correlation, or
  generation no longer matches. Gateway cancels the active cognition task where
  possible; if an upstream ignores cancellation, the late response is not
  returned or played and only its hash is appended to a late-result-discarded
  receipt. Interruption evidence monotonically reconciles browser-audio,
  LiveKit-control, provider-cancel, and cognition-cancel observations without
  rewriting prior evidence.
- A network-ambiguous request is never submitted again automatically. The client
  queries the session-scoped turn status by stable ID; proven terminal outcomes
  are receipt-bound, while an unproven outcome is shown as `NOT CONFIRMED`.
  Only an explicit Retry creates a fresh, linked turn.
- Conversational interruption remains orthogonal to capability-action state;
  Stop never implies action cancel, approval, or rejection.
- Implementation slice 6 is source-present: camera and screen transmission now
  require server-authoritative consent leases bound to the exact paired device,
  Senses session, source, and mode. One-shot leases expire after 120 seconds and
  are consumed by one accepted frame; bounded leases expire after 15 minutes,
  enforce one keyframe every 15 seconds, require monotonic sequence numbers, and
  cannot be renewed without a new user gesture.
- Camera and screen preview remain separate local-only streams. The shell now
  exposes distinct screen controls, visible bounded-lease countdowns, and
  immediate camera/screen shutdown on explicit stop, permission loss,
  backgrounding, page hide, or freeze. Neither preview path publishes a
  continuous LiveKit video track.
- Gateway validates the exact session capability, consent/device/source binding,
  capture timestamp, byte limit, declared MIME versus file signature, actual
  dimensions, and sequence before cognition. Raw keyframes are written only as
  mode-0600 ephemeral working files, deleted in the terminal-turn `finally`
  boundary, and covered by a five-second crash sweeper with headroom below the
  frozen five-minute orphan limit.
- Persistent vision evidence contains hashes, byte count, dimensions, source,
  consent/turn/correlation IDs, timestamps, provider/model IDs, outcome, and
  deletion receipt only. `VisionFrameReceipt` no longer requires or accepts a
  persistent storage path; raw bytes and prompt text are absent from the
  consent/frame SQLite ledgers and browser-sense event receipts.
- The v1 session issuance path accepts only `GOVERNED_PIPELINE`.
  `NATIVE_AUDIO_EXPERIMENTAL` remains lab-only and cannot enter v1 evidence.
- The overall Senses v1 contract is not yet fully `IMPLEMENTED`, `WIRED`,
  `CONFORMED`, `ACTIVE`, or `FOUNDER-PROVEN`. No host capability gate changes
  merely because slices 1-6 are source-present. The Gemini adapter is not yet
  the active LiveKit worker path, `Aoede` is not Founder-auditioned or locked,
  and AionUi/Telegram presentation, browser/PWA execution, LiveKit grant
  revocation, credentialed provider execution, and Founder host evidence still
  require their own wiring and proof.

## Next Senses implementation slice

Bundle browser dependencies, add the installable PWA shell and a safe
service-worker cache policy, then prove desktop/mobile foreground suspension,
cold/warm launch behavior, and zero caching of raw media, authentication
responses, cookies, tokens, or sensor payloads. Keep Senses source-present and
do not claim mobile or host conformance before real browser/PWA evidence.

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
- **Merged:** PR #34 merged to main at `055f609e314d6d9064e8a237cedb4e7bf33d4178`;
  PR #39 (docs continuity) merged after it. AETHER_HOME migration is COMPLETE
  (receipt `20260806T221720Z`) — it must NOT be re-run. The remaining Founder
  host-proof sequence (after the release-promotion/shared-tunnel source patch
  merges) is: stage exact latest `main` -> `promote-aether-release.ps1` (reconcile
  Gateway/Watchdog only, no migration) -> bcrypt hash interactive (temp `.txt`,
  `icacls` SYSTEM+Admins; installer removes it) -> Caddy basic auth (ADR-0053) ->
  local auth proof (production Caddyfile + proof echo) -> `update-shared-tunnel.ps1`
  origin `:80 -> :8080` on tunnel `8f53133` -> Dee authorizes public cutover ->
  public proof + recovery receipts CONFORMED.

## Host state (2026-08-07) — migration COMPLETE; ingress blocked by source patch

- **AETHER_HOME migration: COMPLETE**, do not re-run. Receipt
  `C:\aether\migration-evidence\20260806T221720Z\aether-quiescent-migration-20260806T221720Z.json`
  verdict `PASS_READY_FOR_PRODUCTION_SERVICE_INSTALL` (source `C:\aether\home` ->
  rollback preserved; canonical target `C:\ProgramData\Aether`, 20/20 DB,
  mismatches 0, ACL protected SYSTEM+Administrators). `C:\aether\home` no longer
  exists (moved to `C:\aether\home.rollback-20260806T221720Z`).
- **Active release on VPS: `81582f70c0ccd3d7b32d364b2be6784cff5ffc31`**
  (immutable). Production services running: `AetherGateway` (:8000, health ok),
  `AetherWatchdog`, `AetherCaddy` (:8080). `AetherSenseWorker` and
  `AetherCloudflareTunnel` absent (per design: no sense-worker; shared tunnel).
- **`main` = `a14aac7d0bc3954919665da1d6c17ca88f1b904d`** (after PR #39). Repo
  HEAD asserted exact.
- **Founder ingress host: NOT CONFORMED.** `https://aethers.my.id` currently
  serves IIS welcome page (tunnel config maps `aethers`/`www` -> `localhost:80`);
  Caddy :8080 has no basic auth yet; `founder-auth.caddy` absent.
- **Ingress is BLOCKED by a release-promotion / shared-tunnel source patch**
  (PR `agent/release-promotion-shared-tunnel`):
  - `install-aether-services.ps1` previously ran `icacls /inheritance:e` which
    can re-enable inheritance and weaken the AETHER_HOME DACL — now uses governed
    `Ensure-ProtectedAetherHome` (new=apply protected exact, existing=assert only).
  - `promote-aether-release.ps1` adds governed promotion: stage exact clean main
    SHA to a new immutable release, reconcile Gateway/Watchdog only (no AETHER_HOME
    migration), manifest binds exact target SHA, auto-rollback to `81582f70` on
    health failure.
  - `update-shared-tunnel.ps1` adds shared-tunnel mode: preserves
    `oc -> :3000`, `jarvis -> :8010`, `http_status:404`; only rewrites
    `aethers`/`www` origins `localhost:80 -> localhost:8080`; no second connector;
    validate + backup + automatic rollback; secret-safe before/after config SHA
    receipt. (No DNS CNAME change needed — cutover is origin mapping.)
  - Persistent tunnel: single SCM-managed `cloudflared` connector.
- **Next (after this PR reviews + merges):** stage exact latest `main`, promote
  services to the new release (no migration), local auth proof, then Dee
  authorizes the public origin cutover (`:80 -> :8080`), public proof, and
  recovery receipts.
