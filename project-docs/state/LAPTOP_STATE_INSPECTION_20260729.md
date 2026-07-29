# Laptop State Inspection — 2026-07-29

## Scope

Evidence inspected:

- Founder PowerShell output from `AETHER_STATE_INSPECT.ps1`;
- uploaded `runtime_state.zip`;
- current consolidated.1 source behavior;
- original `hermes-brain` inventory for continuity comparison.

The uploaded archive contains only `runtime_state/`, not the complete `AETHER_HOME`. Therefore this inspection uses the generated state report as the authoritative database map and does not claim to inspect database rows, event logs, workspace files, or Obsidian note contents directly.

## Confirmed live state

- `AETHER_HOME`: `C:\Users\hp\AppData\Local\Aether`
- canonical memory records: 47
- retrieval index records: 47
- memory/index alignment: yes
- cognitive sessions: 6
- session messages: 76
- Obsidian Markdown projections: 6
- trust score: 28.5, updated 2026-07-29T08:53:35Z

## Empty or inactive stores

- governed knowledge proposals/evidence/decisions: 0
- Skill Factory candidates/registry/usage/lifecycle: 0
- runtime invocations: 0
- workspace bindings: 0
- root operational MemoryTool FTS entries: 0
- mission plans/outcomes/step attempts/value evidence: 0

## Test-shaped state

The following counts match deterministic first-pulse/demo flows and must be preserved as test evidence, not treated as production learning:

- evolution: one candidate/evaluation/decision/learning/lineage and four triggers
- mission store: three opportunity briefs and no executable mission state

The v1 inspector omitted opportunity, experiment, web-intelligence, fleet, and Browser Senses databases. The internal v2 inspector now includes them; they will be re-inspected at Laptop Baseline Freeze.

## Governance state

- pending action rows: 9
- immutable approval records: 7
- status distribution unavailable in the uploaded evidence

The full pending-actions database must be migrated intact. Expired requests will be swept by the runtime; unresolved pending requests must not be silently re-executed after VPS migration.

## Defects discovered

1. `START_AETHER_WINDOWS_ALPHA.ps1 -Action Status` accessed `RuntimeInformation.OSDescription` directly and failed on the Founder's Windows PowerShell/.NET surface.
2. `profile_start.json` did not exist. The behavior monitor loaded a new observation epoch at every Gateway restart, preventing trust-profile graduation from accumulating over days.
3. Inspector v1 did not enumerate all composition-root SQLite stores.
4. Expected runtime-status and approval-status JSON files were absent from the uploaded archive.

## Internal fixes staged

- portable OS description and architecture fallbacks;
- persistent behavior-monitor profile observation epoch;
- inspector schema v2 with status grouping, behavior-monitor state, directory sizes, and complete composition-root database map;
- no release artifact generated before Laptop Baseline Freeze.

## Migration classification

### Carry as canonical state

- sessions database;
- canonical memory database;
- retrieval index;
- knowledge proposal store;
- Skill Factory store and directories;
- pending-actions/approval database;
- event receipts;
- current workspace;
- current trust/quarantine state;
- live provider-independent configuration excluding secrets from manifests.

### Carry as rebuildable projection

- Obsidian vault;
- retrieval index if reconstruction is required;
- generated reports and indexes.

### Carry as historical test evidence, not production truth

- deterministic evolution demo records;
- opportunity/demo briefs;
- reversible experiment demo records;
- Browser Senses test sessions and camera frames where retained by policy.

### Archive or retire after evidence capture

- empty root `aether_hub.db` operational MemoryTool FTS store;
- absent old Core hub/governance/knowledge-graph databases;
- expired approval requests after receipt preservation.
