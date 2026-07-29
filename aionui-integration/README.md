# Aether Integration Pack for AionUi v2

This pack adds Aether operator pages to an AionUi source checkout while keeping Aether Gateway as a replaceable sidecar.

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

`--wire-router` patches only two known AionUi v2 anchors:

- the lazy page import;
- the protected `/senses` route.

If upstream layout changed, the installer refuses automatic modification. Sidebar wiring remains explicit because AionUi navigation components evolve more frequently than route structure.

## Runtime topology

```text
AionUi renderer
  → /#/senses
  → same-origin iframe /senses
  → Aether Gateway browser-sense API
```

AionUi does not own Aether identity, memory, cognition, or governance.

## Required reverse proxy routes

```text
/senses*              → Aether Gateway
/api/browser-senses*  → Aether Gateway
/                      → AionUi WebUI
```

## Validation required in target checkout

```bash
bun run lint
bun run test
bun run webui:prod:remote
```

The release container does not include the complete upstream AionUi dependency tree, so it does not claim a full upstream package build.
