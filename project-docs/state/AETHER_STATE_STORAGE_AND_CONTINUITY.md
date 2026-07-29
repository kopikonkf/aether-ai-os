# Aether v0.19.2 State Storage and Legacy Continuity

## Decision

Mutable state is intentionally outside the release folder. Code is replaceable; Aether state survives release replacement and VPS migration through `AETHER_HOME`.

### Windows default

```text
%LOCALAPPDATA%\Aether
```

For Founder Dee's proven laptop run this resolved to:

```text
C:\Users\hp\AppData\Local\Aether
```

## Canonical paths

```text
AETHER_HOME\sessions\cognitive-sessions.sqlite3
AETHER_HOME\memory\canonical-episodes.sqlite3
AETHER_HOME\memory\retrieval-index.sqlite3
AETHER_HOME\memory\knowledge-proposals.sqlite3
AETHER_HOME\skills\skill-factory.sqlite3
AETHER_HOME\skills\registry\
AETHER_HOME\obsidian\vault\
```

Promoted knowledge is written to `canonical-episodes.sqlite3` with namespace `knowledge`. Proposal, evidence, and terminal decision records live in `knowledge-proposals.sqlite3`. Obsidian is a projection only.

## Original source boundary

The original code used `HERMES_HOME` and a sibling `hermes-brain` directory containing:

- `hermes_hub.db`
- `skills/*.md`
- `knowledge/cka/registry.json`
- `runtime_state/knowledge/*`
- `obsidian/vault/*`
- `20_Dee_Workspace/*`

v0.19.2 renamed the state boundary to `AETHER_HOME`, added new SQLite memory/skill/knowledge contracts, and did not automatically transform legacy data into those contracts.

The existing `scripts/migrate_state.py` is a generic directory copy. It preserves bytes but does not perform semantic migration. Therefore old skills and knowledge must not be called active until they pass the new candidate/evidence/governance pipelines.

## Safe preservation policy

`MIGRATE_LEGACY_AETHER_BRAIN.ps1`:

- defaults to dry-run;
- hashes every legacy file;
- creates only an inert archive under `AETHER_HOME\legacy\archives\original-brain` when `-Apply` is explicit;
- never writes into current memory, Skill Factory, knowledge, workspace, or live Obsidian paths;
- hash-reports potential-secret files without copying their bytes;
- authorizes zero automatic semantic imports.

## Inspect current state

```powershell
.\AETHER_STATE_INSPECT.ps1
```

The report includes full paths, existence, file sizes, SQLite table names, and row counts without exposing credentials.
