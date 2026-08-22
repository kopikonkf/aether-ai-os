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
  `founder_accepted` audition status (Founder audition ACCEPTED 2026-08-09;
  voice `Aoede` = AUDITION_ACCEPTED, adapter canary = PASS, runtime path
  WIRED:NO / ACTIVE:NO / FOUNDER-PROVEN:NO).
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
- Implementation slice 7 is source-present: `/senses` now exposes a same-origin
  installable manifest with exact `/senses` start/scope, 192/512/maskable PNG
  icons, safe-area layout, and minimum 44-CSS-pixel primary touch targets.
- The browser build locks `livekit-client` 2.17.2 and esbuild 0.28.1 in an npm
  lockfile, commits the reproducible local ESM bundle, and rebuilds/diffs that
  artifact in CI. The Senses app and CSP no longer import or permit a public
  JavaScript CDN at runtime.
- The module service worker owns only an exact build-versioned static-asset
  allowlist. The canonical `/senses` navigation is network-first with one static
  offline-shell fallback; API, health/status, mutation, unknown-query,
  cross-origin, audio, video, frame, transcript, authentication, and sensor
  requests are network-only and never written by the service worker.
- Offline launch is explicitly labelled `OFFLINE — Aether unavailable`; it
  cannot send, capture, perform cognition, or queue a replay. Cache activation
  deletes only prior Aether Senses cache versions, while credential revocation
  explicitly purges every Aether Senses managed cache.
- PWA lifecycle state is separate from Aether availability. Network loss,
  backgrounding, page hide, and freeze synchronously stop local capture,
  recognition, synthesis, remote audio, and the LiveKit room; returning visible
  or online remains `SUSPENDED` until `Resume senses` is pressed. Resume creates
  a fresh session epoch and never revives a prior turn or sensor lease. A waiting
  service-worker update is activated only by an explicit safe-update gesture.
- Implementation slice 8 is source-present: Browser Senses now reconstructs
  `PROPOSED`, `AWAITING_APPROVAL`, `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`,
  `REJECTED`, and `UNAVAILABLE` presentation from the canonical governed-action
  event journal. The session-scoped status route returns ordered receipts only;
  terminal presentation requires the originating execution/governance event ID,
  and registered capability metadata or the bounded governed-route metadata for
  intentionally hidden skill/coding bodies supplies a deterministic manifest
  hash. That route hash does not activate or claim conformance for an external
  adapter. Raw arguments, action output, secrets, and operator credentials are
  not projected into Senses.
- Senses exposes a safe action card, exact action SHA-256, receipt ID, progress,
  and a presentation-only handoff. It has no approval decision route or control;
  spoken or typed `yes` is explicitly non-authoritative. Pending actions link to
  the AionUi Approval Inbox by approval ID plus full expected action hash, or to
  Telegram `/approvals`.
- AionUi validates the handoff's full expected hash against the main-process
  inbox projection before selecting the action. Telegram `/approvals` renders
  the same shared inbox as exact-hash-bound inline cards; callback signatures
  now bind decision, approval ID, and full action hash. Browser-origin callbacks
  fail closed outside the allowlisted Founder's private chat, and their result
  remains on the originating Senses receipt channel instead of being copied as
  raw output into Telegram.
- Implementation slice 9 is source-present: the governed action path now owns a
  distinct cancellation/reconciliation control boundary. Every control intent
  is bound to a stable `control_request_id`, exact action SHA-256, Browser
  Senses session, authenticated principal, and observed ledger receipt. Reuse
  of the same ID with different evidence fails closed; an exact replay reads the
  prior control receipt and never calls the adapter again.
- Action execution is shielded from the lifetime of its HTTP waiter. A browser
  timeout or disconnect therefore cannot cancel the backend implicitly or
  authorize a replay. The original execution continues to one authoritative
  terminal receipt; a status-ambiguity intent emits `RECONCILING · NOT
  CONFIRMED` and performs lookup only. A later completion/failure receipt moves
  that same action monotonically to a confirmed terminal state.
- Cancellation is available only when the exact registered capability declares
  support and its adapter implements an acknowledgement port. Senses exposes a
  separate receipt-bound cancel control only while that action is `RUNNING`;
  `Stop Aether`, Escape, speech barge-in, disconnect, and suspension still do
  not imply capability cancellation. Unsupported and unacknowledged cancel
  outcomes remain non-terminal and are not resubmitted. A confirmed cancel
  projects `CANCELING` then `CANCELED`; any late adapter result is hash-only
  discarded and cannot overwrite the cancellation receipt.
- No existing production capability was newly marked cancellation-capable by
  this slice. Current adapters retain the safe default `cancel_supported=false`
  unless they already provide and declare the exact acknowledgement contract.
  The new lifecycle is exercised against bounded in-process conformance fakes;
  real host/device trials remain separate evidence.
- The v1 session issuance path accepts only `GOVERNED_PIPELINE`.
  `NATIVE_AUDIO_EXPERIMENTAL` remains lab-only and cannot enter v1 evidence.
- Implementation slice 10 is source-present and NON-ACTIVATION: the LiveKit
  grant ledger records every issued participant grant bound to its exact Senses
  session, and a device/session revocation invalidates those grants (append-only
  evidence, `BROWSER_SENSE_LIVEKIT_GRANT_ISSUED` /
  `BROWSER_SENSE_LIVEKIT_GRANT_REVOKED` events, a usable/revoked/expired status
  check, and an operator-authenticated grant status route). A revoked or expired
  grant is refused by `assert_usable`; re-issuance after revocation is not
  granted. The `CredentialedVoiceWorker` runs exactly one governed exact-text
  Gemini TTS synthesis with an env-resolved credential (`env://` reference
  only), a hash-only `VoiceTurnReceipt`, honest browser-speech/text-only
  fallback proof, and an explicit non-activation gate — it is never wired into
  the LiveKit worker and raises no capability to `ACTIVE`/`CONFORMED`/
  `FOUNDER-PROVEN`. `aether-voice-worker` CLI is dry-run by default and only
  performs a live provider call behind an explicit operator flag.
- Platform T0 (`phases/` phase-observer + `aether.work-packet.v1`) is developed
  on its own independent branch and is NOT part of this Senses PR.
- The overall Senses v1 contract is not yet fully `IMPLEMENTED`, `WIRED`,
  `CONFORMED`, `ACTIVE`, or `FOUNDER-PROVEN`. No host capability gate changes
  merely because slices 1-10 are source-present. The Gemini adapter is not yet
  the active LiveKit worker path. The Founder Alpha voice `Aoede` has passed its
  audition (`AUDITION_ACCEPTED`, 2026-08-09) and the exact-text adapter has a
  live credentialed canary `PASS`, but the Senses Gemini runtime path remains
  `WIRED:NO / ACTIVE:NO / FOUNDER-PROVEN:NO`. Real browser/PWA installation and
  launch evidence, real-device capability cancellation/reconciliation trials,
  and Founder host evidence still require their own wiring and proof. Slice 10
  does not activate a new capability adapter or raise any named capability to
  `ACTIVE` or `FOUNDER-PROVEN`.

## Platform T0 (parallel workstream)

- Platform T0 is source-present and proposal-only. A `PhaseObserver` subscribes
  to the canonical EventBus, projects each durable event into a bounded
  provider-neutral fact, and records a `knowledge_candidate` memory record in
  the `phases` namespace (kind OBSERVATION, `promotion_status=not_promoted`,
  provenance with the originating event IDs). It never promotes, mutates, or
  self-approves; a reentrancy guard prevents echo loops from the observer's own
  emitted `MEMORY_RECORDED` event.
- The versioned `aether.work-packet.v1` schema is hash-bound and
  transition-safe: every packet carries its schema version, exact status, and a
  deterministic SHA-256 over the full unsigned payload; an integrity mismatch
  or a foreign schema is rejected, status transitions must follow the allowed
  transition graph, and a terminal state (completed/failed/cancelled) can never
  be reopened.
- Tests: `aether-core/tests/test_phases_t0.py` (6 passed). This workstream is
  independent from the Senses slice-10 PR and ships on its own branch.

## Next Senses implementation slice

The Gemini exact-text voice path has now passed its live credentialed canary
(`PASS`, single Founder-approved call) and the voice `Aoede` has passed Founder
audition (`AUDITION_ACCEPTED`, 2026-08-09). The remaining live evidence is the
LiveKit provisioning + runtime wiring and an end-to-end LiveKit
grant issue→revoke→disconnect→refuse trial against a real session, then the
Android installed-PWA / acceptance matrix. Keep Senses source-present and do not
claim mobile, host, or capability conformance before that evidence exists. Slice
10 remains non-activated until its own evidence passes; the Gemini
runtime path stays `WIRED:NO / ACTIVE:NO / FOUNDER-PROVEN:NO` until then.

## Next operational step

- **Phase B exact `742631871ee2967583c2e2f0e5a9f02c91c880a6` has PASS** (promotion
  receipt, services bound to `C:\aether\releases\74263187...`, /health /senses
  /api/browser-senses/status 200, ACL protected, Caddy public 401 with the
  live host-agnostic hot-fix).
- **PR #47 MERGED** `main@9b47560a9df3dd636b0deba4e6c41276b34ca868`; controlled
  Caddy reconcile PASS; full proof contract **PASS** — receipt v2
  `C:\ProgramData\Aether\runtime\ingress\caddy-reconcile-receipt-v2.json`
  (blob `53b7cea...`, receipt sha256 `3d698fcb...`, host matrix, authenticated 200,
  invalid 401, header-strip, public aethers+www, backup/recovery disposition).
- **Phase C (Senses) HOLD-RELEASE-READY**: supplementary proof PASS; awaiting Chief
  Architect release of hold (verdict #5226495226). No approval Founder required.
- Next after release: device matrix (Windows Chromium + Android PWA) -> provider/LiveKit
  proof.
- Do NOT repeat Phase A/B or any full Fase A–E.

## Cloudflare ingress PR #47 (host-agnostic Caddy listener, 2026-08-08)

- Based on exact `main@742631871ee2967583c2e2f0e5a9f02c91c880a6`.
- **Why:** the VPS hot-fix found that the production Caddyfile site block
  `http://127.0.0.1:8080` only matched Host `127.0.0.1`, so tunnelled requests
  with Host `aethers.my.id` / `www.aethers.my.id` received an **empty 200 with no
  Basic challenge** (founder auth bypassed on public route). The fix (applied
  live and verified) is now canonicalized here.
- **Change:** `deploy/windows/Caddyfile` listener `http://:8080` +
  `bind 127.0.0.1` (loopback-only, host-agnostic); import
  `founder-auth.caddy` + `header_up -Authorization` on every handler unchanged.
  `deploy/cloudflare/README.md` updated; regression
  `test_real_production_caddyfile_host_agnostic` (real Caddy + PRODUCTION Caddyfile,
  Host `aethers.my.id` / `www.aethers.my.id` / `127.0.0.1`): unauth 401 + Basic
  challenge (never 200-empty), correct creds 200, wrong creds 401, no
  `Authorization` forwarded to echo upstream, `caddy validate` passes. Real-Caddy
  integration renderer updated for the new listener form.
- **Local:** integration `7 passed`; assets/probe behavior `14 passed`;
  standalone `caddy validate` OK. CI boundary proof runs (not skipped) via
  `AETHER_INGRESS_INTEGRATION=1`.
- **Not included:** `cloudflared --metrics 127.0.0.1:20120` treated as separate
  source drift. No deploy/restart/promotion/tunnel/DNS-IIS-Cloudflare mutation.
- **PR:** https://github.com/kopikonkf/aether-ai-os/pull/47

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
  host-proof sequence is: stage exact latest `main` -> `promote-aether-release.ps1`
  (reconcile Gateway/Watchdog only, no migration) -> bcrypt hash interactive (temp `.txt`,
  `icacls` SYSTEM+Admins; installer removes it) -> Caddy basic auth (ADR-0053) ->
  local auth proof (production Caddyfile + proof echo) -> `update-shared-tunnel.ps1`
  origin `:80 -> :8080` on tunnel `8f53133` -> Dee authorizes public cutover ->
  public proof + recovery receipts CONFORMED.

## Host state (2026-08-07) — migration COMPLETE; ingress source merged, host NOT CONFORMED

- **AETHER_HOME migration: COMPLETE**, do not re-run. Receipt
  `C:\aether\migration-evidence\20260806T221720Z\aether-quiescent-migration-20260806T221720Z.json`
  verdict `PASS_READY_FOR_PRODUCTION_SERVICE_INSTALL` (source `C:\aether\home` ->
  rollback preserved; canonical target `C:\ProgramData\Aether`, 20/20 DB,
  mismatches 0). `C:\aether\home` no longer exists.
- **Active release on VPS: `81582f70c0ccd3d7b32d364b2be6784cff5ffc31`**
  (immutable). Production services running: `AetherGateway` (:8000, health ok),
  `AetherWatchdog`, `AetherCaddy` (:8080). `AetherSenseWorker` and
  `AetherCloudflareTunnel` absent (per design: no sense-worker; shared tunnel).
- **Founder ingress host: NOT CONFORMED.** `https://aethers.my.id` currently
  serves IIS welcome page (tunnel config maps `aethers`/`www` -> `localhost:80`);
  Caddy :8080 has no basic auth yet; `founder-auth.caddy` absent.
- **AETHER_HOME DACL on the live host is NOT yet protected** (`AreAccessRulesProtected=false`,
  extra SIDs: Owner S-1-3-0, Users S-1-5-32-545 ReadAndExecute/Write) because the
  active release's installer still runs `icacls /inheritance:e`. The new installer
  (PR #40) is fail-closed, so Fase A (exact ACL setter + tree-wide postcondition)
  MUST run before any promote.
- **Release-promotion / shared-tunnel source is MERGED to main at `5256751`
  (PR #40). Host mutation is NOT executed and awaits Founder authorization.**
  Source behaviour:
  - `install-aether-services.ps1`: removed `/inheritance:e`; `Ensure-ProtectedAetherHome`
    (new=apply protected exact, existing=assert only); `-TargetSha` bound to manifest.
  - `promote-aether-release.ps1`: `-ExpectedTargetSha` is mandatory (provenance guard);
    **`-Start` is required for any mutating promotion** (restart + live running-path +
    health gates are never optional and never skipped); stage via temp dir + atomic
    publish; `Invoke-Git`/`Invoke-GitCapture` wrappers so Windows PowerShell 5.1 cannot
    turn git's normal stderr progress into a terminating error; **restart failures are
    never swallowed**; running-path proof correlates the LIVE `Win32_Service.ProcessId`
    with `Win32_Process.CommandLine` bound to the release; **universal rollback envelope
    wraps EVERY failure after service-configuration mutation** using the CURRENT safe
    installer against `81582f70`, proving running path + health + DACL +
    **live `AETHER_HOME\services\service-manifest.json` provenance** rebound to the
    rollback release, and **`rollback_proven` is the aggregate of ALL of those
    postconditions** (a manifest mismatch or DACL failure leaves the aggregate
    FALSE with an observation-derived error); `targetRelease` is NEVER deleted once services may reference it
    (only a publish that never touched services is removed for retry-safety);
    retry-safe (reuse matching release metadata, remove partial publish); boolean
    receipt with target_sha + paths; DACL asserted before AND after.
  - `update-shared-tunnel.ps1`: rewrites ONLY the two Aether `service:` scalars
    (`:80 -> :8080`), preserves `oc`/`jarvis`/`http_status:404`; validate-before-apply
    + atomic replace + backup; **connector binding via `Win32_Service.ProcessId`
    correlated with `Win32_Process.CommandLine` (exact CIM), exact config-derived
    tunnel UUID** (never a hard-coded prefix, never the UUID-in-cmdline assumption);
    **the SCM connector is stopped via `Stop-Service` + wait (never `Stop-Process`),
    then only positively matched stale direct PIDs are stopped** and stop failures are
    never swallowed, preserving unrelated connectors; `Assert-Administrator` runs before
    `-Apply/-Start` mutation; every receipt field is initialized and every observation
    null-checked; fail-closed restore on every post-replace failure, and **recovery
    requires the exact-one governed connector assertion plus observed readiness**
    before `recovery_proven` is set.
  - Executable fault-injection tests run the real `.ps1` through PowerShell on any
    runner via documented env-gated observation seams (default path always real
    CIM/SCM/service control): tunnel success binding + stale-direct handoff,
    restart-failure restore, stale-PID stop-failure, readiness-failure recovery,
    duplicate-connector recovery refusal; promotion success, reuse-existing manifest SHA,
    target-installer failure, rollback failure, health failure, running-path failure,
    old-live-PID after binPath change, restart failure, omitted `-Start`, and live
    service-manifest SHA mismatch.
  - No DNS CNAME change needed — cutover is origin mapping only.
- **Next (after Founder authorizes host mutation):** Fase A (ACL hardening) -> stage exact
  latest reviewed `main` SHA (`-ExpectedTargetSha`) -> promote services (no migration)
  -> bcrypt hash interactive -> Caddy basic auth (ADR-0053) -> local auth proof ->
  shared-tunnel origin cutover (`:80 -> :8080`) -> Dee authorizes public cutover ->
  public proof + recovery receipts.
