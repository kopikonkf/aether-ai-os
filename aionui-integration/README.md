# Aether Integration Pack for AionUi v2

This pack adds Aether operator pages to an AionUi source checkout while keeping Aether Gateway as a replaceable sidecar.

AionUi is the private Founder cockpit. It does not own Aether identity, memory, cognition, governance, action execution, or approval state.

## Generic Approval Inbox

The native page lives at:

```text
packages/desktop/src/renderer/pages/approval-inbox/
```

It provides:

- status counts and pending/history filters;
- bounded approval summaries;
- full exact action SHA-256 inspection;
- risk, scopes, reversibility, request channel, expiry, and bounded context;
- explicit approve/reject reason;
- hash-bound decisions and exact-once replay visibility.

Security boundary:

```text
AionUi renderer
  → bounded IPC request
  → AionUi main process owns AETHER_OPERATOR_TOKEN
  → Aether Gateway /api/approvals
  → shared ApprovalInboxService
  → governed exact action execution and receipt
```

The renderer never receives the operator token, raw action bodies, secret values, unbounded arguments, or action-result output. The renderer requests a decision; the authenticated Gateway remains the approval and execution authority.

Wiring snippets:

```text
integration-snippets/approval-bridge-registration.ts.txt
integration-snippets/approval-preload.ts.txt
integration-snippets/approval-route.tsx.txt
integration-snippets/approval-sidebar.tsx.txt
```

## Unified Senses

The v0.19.2 page lives at:

```text
packages/desktop/src/renderer/pages/unified-senses/
```

It embeds the same-origin `/senses` application and reports Aether sidecar/LiveKit status. Browser permissions remain controlled by Chrome/Android and require HTTPS or localhost.

## Install

```bash
python scripts/install_aionui_integration.py /path/to/AionUi --wire-router
```

`--wire-router` patches only two known AionUi v2 anchors for Unified Senses:

- the lazy page import;
- the protected `/senses` route.

If upstream layout changed, the installer refuses automatic modification. Approval Inbox and other operator-page route/sidebar wiring remain explicit because AionUi navigation components evolve more frequently than the integration pack.

## Runtime topology

```text
AionUi renderer
  → protected operator page
  → typed contextBridge IPC
  → AionUi main-process service
  → loopback/same-origin Aether Gateway API
```

Unified Senses additionally uses:

```text
AionUi renderer
  → /#/senses
  → same-origin iframe /senses
  → Aether Gateway browser-sense API
```

## Required reverse proxy routes

```text
/api/approvals*        → Aether Gateway
/senses*               → Aether Gateway
/api/browser-senses*   → Aether Gateway
/                       → AionUi WebUI
```

Keep Aether Gateway port `8000` loopback-only. The reverse proxy and AionUi main process are the permitted boundaries.

## Validation required in target checkout

```bash
bun run lint
bun run test
bun run webui:prod:remote
```

The Aether repository validates Python APIs, static integration contracts, manifest safety, and source structure. It does not contain the complete upstream AionUi dependency tree, so it cannot claim a full upstream renderer/package build until the pack is installed into a pinned AionUi checkout.
