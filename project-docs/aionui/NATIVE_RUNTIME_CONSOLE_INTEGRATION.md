# Native AionUi Runtime Console Integration

The release integration pack targets the current AionUi v2 layout under
`packages/desktop/src`.

## Included modules

```text
common/aetherFleetTypes.ts
process/services/aetherFleet/AetherFleetService.ts
process/bridge/aetherFleetBridge.ts
renderer/pages/runtime-operations/index.tsx
renderer/pages/runtime-operations/useAetherFleet.ts
renderer/pages/runtime-operations/RuntimeOperations.module.css
```

## Trust path

```text
AionUi renderer
  -> bounded `window.aetherFleet` IPC methods
  -> Electron main process
  -> X-Aether-Operator-Token header
  -> Aether Gateway fleet API
```

The renderer does not receive the token and cannot supply a principal identity.
The principal is resolved by Aether Gateway from trusted deployment config.

## Installation

```bash
python aionui-integration/scripts/install_aionui_integration.py /path/to/AionUi
```

Then apply the snippets in `aionui-integration/integration-snippets` to:

- `packages/desktop/src/preload/main.ts`
- `packages/desktop/src/renderer/components/layout/Router.tsx`
- the main-process bridge registration/bootstrap
- optionally the sidebar navigation component

Run the upstream checks afterwards:

```bash
npm run lint
npm test
npm run package
```

The installer refuses to overwrite existing feature files unless `--force` is
provided and never rewrites shared bootstrap files.
