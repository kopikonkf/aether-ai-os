# Aether v0.19.2 — Capability State Map

## Truth model

A feature is not called "active" merely because a class or test exists.

```text
IMPLEMENTED -> WIRED -> CONFORMED -> ACTIVE -> FOUNDER-PROVEN
```

- **Implemented:** contract and code exist.
- **Wired:** runtime constructs the component and exposes a reachable path.
- **Conformed:** the exact adapter/environment passed a live bounded canary.
- **Active:** configuration enables the component and policy makes it eligible.
- **Founder-proven:** a real end-to-end user execution produced evidence.

## Founder-proven now

- Windows Core/Gateway boot and restart.
- Live model cognition.
- Telegram DM conversation.
- Browser text conversation.
- Camera keyframe vision.
- Browser speech output.
- Authenticated browser-sense session.
- Living Machine MCP mutation surface (`living-mcp.mutation`) — single
  principal `chatgpt` recorded through the full chain
  (`IMPLEMENTED -> WIRED -> CONFORMED -> ACTIVE -> FOUNDER-PROVEN`) on the
  production runtime (ADR-0055 prerequisite P4). Evidence: governed
  `workspace_edit` via Trusted Approval Inbox + local-structured coding
  runtime, OAuth audit attribution `principal_id=chatgpt`. The surface is
  single-operator: no second principal is authorized against it.

## Lifecycle mechanism

- `aether.capabilities.lifecycle` (`aether.capability-lifecycle.v1`) is the
  deterministic tracker for mutation-surface lifecycle per principal. It
  records transitions (append-only JSONL) with observation-derived evidence,
  enforces consecutive stage transitions (fail-closed), and enforces the
  ADR-0055 P4 single-principal gate: at most one founder-proven principal per
  surface, and a second principal cannot become ACTIVE until the first is
  founder-proven. It grants no authority — ActionGovernor and the Trusted
  Approval Inbox remain the sole authority evaluators. Exposed read-only via
  the Living Machine MCP capability manifest (`lifecycle` key).
  Implemented: contract + code exist (aether-core). Wired: runtime
  constructs it and the manifest path is reachable (aether-gateway).
  Conformed: deterministic tests cover transitions, fail-closed evidence,
  and the single-principal gate. Active: recorded per-principal on the host.
  Founder-proven: first principal `chatgpt` recorded end-to-end.

## Wired and test-proven, but not all Founder-proven

- durable memory, retrieval rebuild, and Obsidian projection;
- governed read/write/edit/grep/glob/bash/webfetch/memory tools;
- pending approvals and exact-once continuation;
- skill candidate, verification, activation, and rollback lifecycle;
- internal CEE trigger, failure fingerprint, candidate evaluation, promotion, lineage, and rollback;
- local structured coding runtime and external-runtime protocol;
- runtime driver pack for Codex, OpenCode, Gemini CLI, and Claude Code;
- mission planning, budgets, pause/resume/cancel, outcome and value evidence;
- opportunity candidates, portfolio scoring, mandates, and mission conversion;
- private reversible experiment artifacts, previews, demand signals, and external-action review;
- live-web configuration, source conformance, acquisition, freshness, and discovery APIs.

## Wired but dormant

- Crawl4AI restricted adapter: optional dependency, disabled until configured and conformed.
- Generic public HTTP live adapter: available in code, disabled until configured and conformed.
- LiveKit worker: optional dependency and external service.
- real coding CLI bodies: driver code exists, exact CLI/auth/conformance still required.
- AionUi integrated build and public one-domain deployment.

## Not yet delivered

- public preview-to-production deployment adapter;
- analytics/webhook evidence ingestion;
- waitlist/lead/conversion ledger;
- verified payment/revenue linkage;
- public deployment rollback and kill switch;
- evidence-comparable portfolio reallocation;
- CEE strategy updates from real demand and revenue outcomes.
