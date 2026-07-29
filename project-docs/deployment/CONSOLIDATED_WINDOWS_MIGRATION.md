# Frozen Windows Laptop Baseline Migration

## Boundary

```text
Release folder = replaceable code, configs, wheels, launchers
AETHER_HOME    = mutable memory, events, approvals, skills, workspaces, senses
.env           = local provider/sense configuration and secrets
```

Upgrade from consolidated.1 by extracting the frozen release beside it and copying only `.env`:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd C:\Aether\Aether_OS_v0.19.2-founder-alpha-frozen.1

.\MIGRATE_EXISTING_WINDOWS_RELEASE.ps1 `
  -OldReleaseRoot C:\Aether\Aether_OS_v0.19.2-founder-alpha-consolidated.1

.\AETHER_WINDOWS_READINESS.ps1
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Status
.\AETHER_STATE_INSPECT.ps1 `
  -Output "$env:LOCALAPPDATA\Aether\runtime_state\reports\laptop-baseline-freeze-v2.json"
```

Do not copy `.venv`, `.aether-windows`, PID files, or mutable databases into the new release folder.

## Original brain

The old brain is ancestry and project history, not current autobiographical memory. The migration utility is archive-only:

```powershell
.\MIGRATE_LEGACY_AETHER_BRAIN.ps1 `
  -LegacyBrainRoot C:\path\to\hermes-brain
```

`-Apply` copies non-secret bytes only into an inert legacy archive. It never writes into current memory, Skill Factory, governed knowledge, workspace, or Obsidian projection. Potential secrets remain at the Founder-controlled source location and are represented only by metadata and SHA-256.

## VPS transition

After laptop acceptance:

1. stop the laptop Gateway;
2. create a protected archive of the resolved `AETHER_HOME`;
3. provision the Windows VPS and install the next VPS-ready release;
4. restore state only while the VPS Gateway is stopped;
5. run state inspector v2 and compare canonical counts;
6. do not resume expired or laptop-bound pending actions;
7. retain the laptop backup until Founder acceptance.
