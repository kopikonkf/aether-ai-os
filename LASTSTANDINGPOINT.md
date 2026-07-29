# LASTSTANDINGPOINT

## Current phase

Laptop baseline accepted; GitHub `main` is now the canonical source authority. Windows VPS provisioning remains in progress while deployment foundations and a read-only MCP capability-plane baseline proceed in parallel.

## Accepted baseline

- Build: `v0.19.2-founder-alpha-frozen.2`.
- Windows launcher doctor/stdout bug fixed.
- Gateway healthy on Windows 10; Telegram and Browser Senses live.
- Telegram one-tap approval proven.
- Central CommandRegistry active.
- Governed write proof completed.
- Trust observation epoch persisted in `runtime_state/profile_start.json`.
- State Inspector v2 completed.
- Canonical memory and retrieval index aligned at 51/51.
- Uploaded AETHER_HOME snapshot inspected; 19 SQLite authorities passed integrity checks.

## Telegram presentation status

- Telegram approval cards work on the accepted frozen.2 laptop baseline.
- A conservative safe-HTML `TelegramPresentationAdapter` is now staged in the working tree with escaping, bounded splitting, links, headings/lists, inline/fenced code, and plain-text fallback.
- Cognition receives an authoritative channel-capability snapshot and must not promise unsupported structured Rich Messages or streaming.
- Bot API 10.2 structured Rich Messages remain not implemented and non-blocking.

## Aether CLI decision

- Aether currently has a broad cross-platform developer entrypoint, `python aether_cli.py ...`, plus package commands such as `aether-gateway` and `aether-boot`.
- It does not yet have one stable installed umbrella command named `aether`.
- A first-class thin control-plane CLI is accepted for the VPS-ready release.
- CLI mutations must use the same governance/approval path as Telegram and API.
- The CLI must not duplicate Mind logic or bypass runtime adapters.

## Context continuity decision

- Current session behavior is bounded truncation, not compaction: `SQLiteConversationStore` retains 48 recent messages and deletes older session rows.
- Canonical episodic memory preserves turns separately and lexical retrieval injects up to six relevant records.
- Legacy idle-consolidation/dream modules are not composition-root wired and are not active capability.
- A provider-neutral Context Continuity Engine is accepted as a staged foundation:
  - immutable raw context ledger
  - structured checkpoints
  - protected recent tail
  - tool-output externalization with typed recall handles
  - summary DAG with source lineage
  - soft/hard token thresholds
  - deterministic convergence fallback
  - bounded search/expand/doctor tools
- Do not activate automatic compaction before canary evaluation.

## Skill curation decision

- Existing Skill Factory governance is retained.
- External skill intake is the missing layer.
- External skills must be pinned by commit/hash, classified, normalized, sandboxed, benchmarked, and explicitly activated.
- `mvanhorn/last30days-skill` is reference/nutrition material, not a direct install candidate for current Aether runtime.
- Future Aether-native candidate: `recent-signal-research`, built over SourceCapabilityMesh with bounded credentials and provenance.

## Buzz decision and baseline

- Buzz is approved as a future optional collaboration plane candidate, not a replacement for Aether Mind, AionUi, or governance.
- Aether remains orchestrator; Buzz provides sovereign rooms, signed agent identities, ACP worker connectivity, workflows, git/event context, and future huddle Sense integration.
- Implementation is deferred until after AionUi integration.
- Before implementation:
  - pin exact release/commit and image digests
  - deploy on isolated Linux host/container boundary
  - separate Aether/Founder/worker cryptographic identities
  - define task and result receipt schemas
  - prove read-only subscription, one worker dispatch/result loop, cancellation, restart deduplication, and outage isolation
  - do not auto-ingest Buzz history into canonical memory

## Foundation files staged internally

- `project-docs/foundations/AETHER_CLI_DECISION.md`
- `project-docs/foundations/CONTEXT_CONTINUITY_BASELINE.md`
- `project-docs/foundations/SKILL_CURATION_BASELINE.md`
- `project-docs/foundations/BUZZ_COLLABORATION_PLANE_BASELINE.md`
- `project-docs/foundations/MCP_CAPABILITY_PLANE_BASELINE.md`
- JSON schemas for context checkpoints, external skill candidates, Buzz task envelopes, and Buzz result receipts.

## Plugin and GitHub continuity status

- Atlassian Rovo is not installed. The Founder account currently has no Jira/Confluence site available for authorization.
- GitHub identity and Codex Connector installation are active for `kopikonkf`.
- Private repository `kopikonkf/aether-ai-os` is accessible with admin, maintain, pull, push, and triage permissions.
- Write conformance passed through branch creation, commits, pull requests, CI inspection, failure diagnosis, and branch repair.
- PR #1 and PR #2 were merged on 2026-07-29. `main` contains the sanitized Aether baseline and effective `.gitignore`.
- GitHub `main` is the source-code authority; `LASTSTANDINGPOINT.md` remains the canonical handoff file in the repository.
- Runtime state, secrets, SQLite files, logs, backups, wheels, ZIPs, and local environments must never be committed.

## Parallel deployment foundations staged

1. Telegram safe presentation adapter.
2. Shared `ApprovalInboxService` for Telegram, HTTP/AionUi, and future surfaces, including optional exact action-hash binding.
3. Quiescent `AETHER_HOME` export/import tooling using SQLite backup, quick-check, sidecar exclusion, and SHA-256 manifests.
4. pywin32 `AetherGateway` Windows Service host with loopback binding, virtual service identity, ACLs, automatic start, restart-on-failure, status, and uninstall paths.

Verification so far:
- Core: 148 passed.
- Tools: 52 passed, 1 optional skip.
- Modified cross-package regression slice: 37 passed.
- Python compilation passed.
- Actual Windows Server service and migration behavior remain pending VPS conformance.

## Migration caveat

- Uploaded AETHER_HOME ZIP includes SQLite WAL/SHM files and is suitable for inspection.
- Final VPS migration backup must be quiescent: stop Gateway, checkpoint SQLite, snapshot AETHER_HOME, then verify hashes and integrity.

## Next canonical sequence

1. Provision Windows VPS.
2. Install frozen.2 release and prerequisites.
3. Create persistent Windows service supervision.
4. Create a quiescent laptop AETHER_HOME migration snapshot.
5. Restore and verify AETHER_HOME on VPS.
6. Cloudflare ingress.
7. AionUi/Senses public health.
8. Generic AionUi Approval Inbox.
9. Nutrition conformance.
10. Google TTS audition and fallback proof.
11. One conformed runtime body.
12. Founder acceptance.
13. MVP v0.20.
14. Buzz collaboration-plane mini-project after AionUi and baseline stabilization.

## Windows VPS provisioning gate

Status: in progress; waiting for Founder-provided VPS evidence.

Accepted target:
- Windows Server 2025 or Windows Server 2022 x64 with Desktop Experience.
- 4 vCPU minimum; 8 GB RAM minimum; 80 GB NVMe minimum. Founder's planned 4 vCPU / 56 GB RAM profile is sufficient for current Aether services, but CPU remains the limiting factor for local-model or high-parallelism workloads.
- Stable outbound Internet and fixed public IPv4.
- Provider snapshot/restore capability.
- Public inbound ports closed except RDP restricted to the Founder's current IP during provisioning. Aether Gateway port 8000 must never be opened publicly.

Canonical VPS paths:
- release root: `C:\Aether\releases\Aether_OS_v0.19.2-founder-alpha-frozen.2`
- service-owned AETHER_HOME: `C:\ProgramData\Aether`
- backups: `C:\ProgramData\Aether\backups`
- logs: `C:\ProgramData\Aether\logs`
- service metadata: `C:\ProgramData\Aether\services`

Provisioning acceptance evidence must be secret-safe and include:
- `Get-ComputerInfo` summary for Windows product/version/build/architecture;
- CPU, RAM, and disk free-space summary;
- `Get-NetFirewallProfile` summary;
- Python 3.11.x path/version when installed;
- `AETHER_WINDOWS_READINESS.ps1` output after the frozen.2 release is copied;
- no passwords, tokens, public IP address, `.env`, or provider credentials.

Do not start the full first pulse on the VPS before migration planning because demo commands write synthetic records into AETHER_HOME. Readiness and doctor are safe gates; full `-Action All` occurs after service/data-path preparation.

## GitHub source authority — 2026-07-29

- Repository: `kopikonkf/aether-ai-os` (private).
- Canonical branch: `main`.
- PR #1 merged: effective `.gitignore`, removal of ineffective `gitignore`, and connector write proof.
- PR #2 merged into the proof branch, then PR #1 merged the complete stacked source into `main`.
- Current `main` head after source import: `20fcb4723894fa163f5da8b1c0e05514f04f7317`.
- Sanitized source import contains 619 source, test, documentation, and deployment paths.
- GitHub Actions final import run passed package installation, compilation, Core, Tools, root deployment, isolated Gateway tests, JSON/YAML parsing, and artifact upload.
- MCP dependency is bounded to `mcp>=1.27,<2`; Gateway dev dependencies include `pytest-asyncio`.

## MCP capability-plane baseline — 2026-07-29

- Tracking issue: `#3 Build read-only Aether MCP capability-plane baseline`.
- Active branch: `agent/mcp-capability-plane-baseline`.
- The dormant legacy CKA MCP prototype is being replaced by a read-only Aether Operational MCP service.
- Approved first resources: `aether://status`, `aether://capabilities`, and `aether://handoff`.
- Approved first tools: `aether_status`, `aether_capability_manifest`, `aether_handoff`, bounded `memory_search`, and bounded `artifact_hash_verify`.
- No mutation tools, approval decisions, shell, arbitrary file access, secret access, legacy CKA bulk access, or public HTTP exposure.
- `stdio` is the default transport. Streamable HTTP requires explicit opt-in and loopback binding.
- External MCP client manager, remote OAuth, mutation proposal tools, and generic MCP Builder remain deferred until the first server is conformed and Founder-proven.
