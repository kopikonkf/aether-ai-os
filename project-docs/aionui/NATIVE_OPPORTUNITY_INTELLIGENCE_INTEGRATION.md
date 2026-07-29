# Native AionUi Opportunity Intelligence Integration

## Process boundary

```text
React renderer
  → window.aetherOpportunity
  → preload IPC
  → aetherOpportunityBridge
  → AetherOpportunityService
  → authenticated Aether Gateway
```

The renderer cannot supply an operator identity and never receives the operator token. The token is read by the Electron main process from deployment configuration.

## Included files

```text
common/aetherOpportunityTypes.ts
process/services/aetherOpportunity/AetherOpportunityService.ts
process/bridge/aetherOpportunityBridge.ts
renderer/pages/opportunity-intelligence/index.tsx
renderer/pages/opportunity-intelligence/useAetherOpportunity.ts
renderer/pages/opportunity-intelligence/OpportunityIntelligence.module.css
integration-snippets/opportunity-preload.ts.txt
```

## Bounded IPC methods

```text
snapshot
scout
score
decide
mandate
convert
```

The renderer cannot call arbitrary URLs, change headers, or retrieve credentials through these methods.

## Manual wiring

After running the non-destructive installer, wire:

1. `AetherOpportunityService` in the Electron main-process bootstrap.
2. `registerAetherOpportunityBridge(service)` during bridge registration.
3. `opportunity-preload.ts.txt` into the existing preload.
4. The lazy route `/opportunity-intelligence` into AionUi Router.
5. An optional sidebar entry using AionUi navigation conventions.

Then run:

```bash
npm run lint
npm test
npm run package
```
