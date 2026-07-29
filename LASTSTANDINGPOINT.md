# LASTSTANDINGPOINT

## Current phase

The Founder-accepted laptop baseline remains `v0.19.2-founder-alpha-frozen.2`. GitHub `main` is the canonical source authority. Windows VPS provisioning is in progress. The read-only Aether Operational MCP baseline is merged and CI-conformed; local Founder proof remains pending.

## Capability truth model

Use this progression for every capability:

```text
IMPLEMENTED → WIRED → CONFORMED → ACTIVE → FOUNDER-PROVEN
```

Code existence alone never proves runtime activation or Founder acceptance.

## Accepted laptop baseline

- Build: `v0.19.2-founder-alpha-frozen.2`.
- Windows launcher doctor/stdout bug fixed.
- Gateway healthy on Windows 10.
- Telegram and Browser Senses live.
- Telegram one-tap approval proven.
- Central Telegram `CommandRegistry` active.
- Governed write proof completed.
- Trust observation epoch persists in `runtime_state/profile_start.json`.
- State Inspector v2 completed.
- Canonical memory and retrieval index aligned at 51/51.
- Uploaded AETHER_HOME snapshot inspected; 19 SQLite authorities passed integrity checks.
- The accepted laptop runtime is not automatically upgraded by GitHub merges.

## Original brain continuity

- Original brain ancestry and project archives must be preserved.
- Legacy brain material is historical ancestry, not current autobiographical memory.
- Do not bulk inject legacy memories, beliefs, CKA claims, skills, SQLite databases, or `.obsidian` state.
- Do not attach or merge legacy SQLite authorities into current runtime databases.
- Sensitive credential-bearing files remain excluded and must never be committed or copied into model context.
- Legacy items may enter current Aether only through explicit curation, provenance, governance, and promotion.
- Obsidian remains a projection, not an authority.
- Canonical migration authority is the quiescent AETHER_HOME snapshot plus integrity/hash receipts.

## GitHub source authority

- Repository: `kopikonkf/aether-ai-os` (private).
- Canonical branch: `main`.
- PR #1 and PR #2 merged the effective `.gitignore`, GitHub write proof, and sanitized Aether source baseline.
- PR #4 merged the read-only MCP capability-plane baseline.
- Current `main` head after PR #4: `4dcf2e55df7cc03ef7d53f9a23fbac38c2d510d4`.
- GitHub Actions verifies package installation, compilation, Core, Tools, root deployment tests, isolated Gateway tests, JSON/YAML parsing, and test receipts.
- GitHub connector write flow is proven for branches, commits, pull requests, CI diagnosis, repairs, and review state.
- `LASTSTANDINGPOINT.md` is the canonical cross-session handoff.
- Never commit runtime state, real `.env`, credentials, SQLite/WAL/SHM files, logs, frames, backups, wheels, release ZIPs, caches, or virtual environments.

## Telegram presentation status

- Approval cards remain Founder-proven on frozen.2.
- Safe-HTML `TelegramPresentationAdapter` is merged in GitHub with escaping, bounded splitting, links, headings/lists, inline/fenced code, and plain-text fallback.
- Cognition receives a channel-capability snapshot and must not claim unsupported structured Rich Messages or streaming.
- Generic Bot API structured Rich Messages remain deferred and non-blocking.
- GitHub merge does not mean the adapter is installed or active on the accepted laptop/VPS runtime.

## Shared Approval Inbox status

- Shared `ApprovalInboxService` is merged for Telegram, HTTP/AionUi, future CLI, and future collaboration surfaces.
- It supports filtering, expiry handling, exact decisions, optional action-hash binding, and exact-once resume.
- AionUi Approval Inbox UI remains pending.
- No surface may bypass the same governed pending-action authority.

## Deployment foundations merged

1. Telegram safe presentation adapter.
2. Shared `ApprovalInboxService`.
3. Quiescent `AETHER_HOME` export/import tooling using SQLite backup, quick-check, sidecar exclusion, and SHA-256 manifests.
4. pywin32 `AetherGateway` Windows Service host with loopback binding, virtual service identity, ACLs, automatic startup, restart-on-failure, status, and uninstall paths.

Actual Windows Server service, ACL, restart, migration, and rollback behavior remain pending VPS conformance.

## MCP capability-plane baseline

- Tracking issue #3 is closed as completed.
- PR #4 is merged into `main`.
- Installed entrypoint: `aether-mcp`.
- Default transport: local `stdio`.
- Streamable HTTP requires explicit opt-in and is restricted to loopback.
- Resources:
  - `aether://status`
  - `aether://capabilities`
  - `aether://handoff`
- Tools:
  - `aether_status`
  - `aether_capability_manifest`
  - `aether_handoff`
  - bounded read-only `memory_search`
  - root-bounded `artifact_hash_verify`
- Advisory prompt: `aether_operational_context`.
- Security boundary:
  - no mutation tools
  - no approval decisions
  - no shell
  - no arbitrary file reads
  - no secret contents
  - no legacy CKA bulk access
  - no public MCP exposure
  - no state creation for fresh AETHER_HOME reads
- CI conformance:
  - 50 Gateway modules
  - 109 tests passed
  - 0 skipped
  - 0 failed modules
  - exact MCP stdio handshake and capability enumeration passed against `mcp>=1.27,<2`
- Current classification:
  - service and contracts: `IMPLEMENTED`
  - package entrypoint and stdio registration: `WIRED`
  - protocol and read-only boundaries: `CONFORMED`
  - installed on Founder laptop: `NO`
  - `ACTIVE`: `NO`
  - `FOUNDER-PROVEN`: `NO`
- Local proof runbook:
  - `project-docs/testing/MCP_FOUNDER_LOCAL_PROOF_WINDOWS.md`
- Deferred until real patterns justify extraction:
  - external MCP client manager
  - MCP server registry and credential references
  - remote OAuth
  - mutation proposal tools
  - generic MCP Builder
  - public ingress

## Aether CLI decision

- A broad developer entrypoint exists: `python aether_cli.py ...`.
- Package commands include `aether-gateway`, `aether-sense-worker`, and `aether-mcp`.
- One stable installed umbrella command named `aether` does not yet exist.
- The accepted thin control-plane CLI must not duplicate Mind logic or bypass governance/runtime adapters.
- CLI mutation commands must use the same governed action and approval path as Telegram and API.

## Context continuity decision

- Current active-session behavior is bounded truncation, not true compaction.
- `SQLiteConversationStore` retains 48 recent messages and deletes older session rows.
- Canonical episodic memory preserves turns separately; lexical retrieval injects bounded relevant records.
- Legacy idle-consolidation/dream modules are not composition-root wired and are not active.
- Accepted staged Context Continuity Engine:
  - immutable raw context ledger
  - structured checkpoints
  - protected recent tail
  - tool-output externalization with typed recall handles
  - summary DAG with source lineage
  - soft/hard token thresholds
  - deterministic convergence fallback
  - bounded search/expand/doctor tools
- Do not activate automatic compaction before canary evaluation.

## Skill curation and nutrition decision

- Existing Skill Factory governance is retained.
- External skill intake remains the missing layer.
- External skills must be pinned by exact commit/hash, classified, normalized, sandboxed, benchmarked, explicitly approved, observed, revised, and archived when needed.
- `mvanhorn/last30days-skill` remains reference/nutrition material, not a direct runtime install.
- Future Aether-native candidate: `recent-signal-research` over `SourceCapabilityMesh` with bounded credentials, freshness, provenance, contradiction handling, and cited synthesis.
- Nutrition conformance remains pending in the operational sequence.

## Buzz collaboration-plane decision

- Buzz is an optional future collaboration plane, not a replacement for Aether Mind, AionUi, memory authority, or governance.
- Implementation starts only after AionUi and baseline stabilization.
- Before deployment:
  - pin exact Buzz release/commit and container image digests
  - deploy in an isolated Linux/container boundary
  - separate Founder, Aether, and worker cryptographic identities
  - define signed task/result receipts and stop conditions
  - prevent automatic Buzz-history ingestion into canonical memory
  - prove cancellation, restart deduplication, outage isolation, and bounded context capsules
- Huddle is a future multi-party audio Sense, not an initial authority surface.

## Canonical operational sequence

Completed or accepted foundation:

```text
inspect current state
→ preserve original brain continuity
→ central Telegram command registry
→ Telegram regular/safe-rich presentation adapter
→ Aether Operational MCP baseline
```

Active executable sequence:

```text
provision Windows VPS
→ install current accepted release and prerequisites
→ persistent Windows services
→ quiescent AETHER_HOME migration
→ restore and verify AETHER_HOME on VPS
→ Cloudflare ingress
→ AionUi/Senses public health
→ generic AionUi Approval Inbox
→ nutrition conformance
→ Google TTS audition and fallback proof
→ one conformed runtime body
→ Founder Acceptance
→ MVP v0.20 Governed Shipping
```

`persistent Windows services` intentionally precedes production restore so the service identity, canonical paths, ACLs, stop/start behavior, and rollback boundary exist before migrated state becomes active.

Parallel non-blocking MCP gate:

```text
install current GitHub main in a separate local development checkout
→ register aether-mcp in a local Codex client
→ enumerate exact MCP capabilities
→ read LASTSTANDINGPOINT
→ call aether_status
→ perform one bounded memory_search
→ verify one artifact hash
→ compare repository and AETHER_HOME before/after
→ prove zero mutation
→ classify ACTIVE and FOUNDER-PROVEN
```

Post-Founder-Acceptance collaboration sequence:

```text
Founder Acceptance
→ MVP v0.20 Governed Shipping
→ Buzz Collaboration Plane spike
→ one isolated room
→ Founder and Aether identities
→ one conformed worker agent
→ one signed bounded task/result loop
→ cancellation and restart-dedup proof
→ bounded multi-agent orchestration
→ huddle integration as a governed Sense
```

Do not jump directly to multi-agent orchestration or huddle before the one-room, one-worker, signed-loop proof passes.

## Windows VPS provisioning gate

Status: in progress; waiting for secret-safe Founder evidence.

Accepted target:

- Windows Server 2025 or Windows Server 2022 x64 with Desktop Experience.
- 4 vCPU minimum.
- 8 GB RAM minimum.
- 80 GB NVMe minimum.
- Founder's planned 4 vCPU / 56 GB RAM profile is sufficient for current services; CPU is the likely bottleneck for local models or high parallelism.
- Stable outbound Internet and fixed public IPv4.
- Provider snapshot/restore capability.
- Public inbound ports closed except RDP restricted to the Founder's current IP during provisioning.
- Gateway port `8000` must never be exposed publicly.

Canonical VPS paths:

```text
release:
C:\Aether\releases\Aether_OS_v0.19.2-founder-alpha-frozen.2

service-owned AETHER_HOME:
C:\ProgramData\Aether

backups:
C:\ProgramData\Aether\backups

logs:
C:\ProgramData\Aether\logs

service metadata:
C:\ProgramData\Aether\services
```

Provisioning evidence must include only:

- Windows product/version/build/architecture;
- CPU, RAM, and disk summary;
- Windows Firewall profile summary;
- Python 3.11.x path/version;
- `AETHER_WINDOWS_READINESS.ps1` output after the frozen.2 release is copied.

Never include passwords, tokens, public IP addresses, `.env`, provider credentials, or API keys.

Do not run the full first pulse on the VPS before service/data-path and migration preparation because demo commands can write synthetic state.

## Migration caveat

- The previously uploaded AETHER_HOME ZIP contained WAL/SHM files and was valid for inspection only.
- Final migration must be quiescent:
  - stop Gateway and every writer
  - verify no listener/writer remains
  - checkpoint SQLite
  - create a clean snapshot
  - generate SHA-256 manifest
  - verify source integrity
  - transfer
  - restore under service-owned paths
  - normalize ACLs
  - verify destination integrity and hashes
  - boot with controlled execution
- Never treat a live-copy ZIP as the final migration artifact.

## Foundation documents

- `project-docs/foundations/AETHER_CLI_DECISION.md`
- `project-docs/foundations/CONTEXT_CONTINUITY_BASELINE.md`
- `project-docs/foundations/SKILL_CURATION_BASELINE.md`
- `project-docs/foundations/BUZZ_COLLABORATION_PLANE_BASELINE.md`
- `project-docs/foundations/MCP_CAPABILITY_PLANE_BASELINE.md`
- `project-docs/testing/MCP_FOUNDER_LOCAL_PROOF_WINDOWS.md`
- JSON schemas for context checkpoints, external skill candidates, Buzz task envelopes, and Buzz result receipts.

## Non-negotiable authority rules

- Aether is the Mind/orchestration authority.
- Runtime bodies are replaceable workers.
- Telegram, browser, voice, camera, and future huddle are Senses.
- AionUi is the private Founder cockpit.
- Buzz is a collaboration plane only.
- MCP and ACP are protocols/connectors, not authorities.
- Reading the world never automatically grants permission to change it.
- Every mutation must pass the same governed action path, approval policy, exact action binding, and authoritative receipt requirements.
