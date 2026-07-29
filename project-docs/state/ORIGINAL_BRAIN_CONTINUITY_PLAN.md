# Original Brain Continuity Plan

## Decision

The original `hermes-brain` is a legacy evidence source, not a database that may be attached directly to the current Aether runtime.

## Source facts

- approximately 7.7 MB;
- 157 files in the extracted source tree;
- 128+ Markdown/knowledge/workspace notes;
- three legacy skills;
- legacy hub database containing 11,722 agent activity rows, 11,035 tool-call rows, and 1,607 messages;
- WAL/SHM companions are present;
- several filenames indicate potential credential/secret material.

## Preservation lanes

1. **Forensic archive** — byte-preserve database, WAL/SHM, logs, and original directory structure with hashes.
2. **Human knowledge archive** — preserve non-sensitive notes inside the inert archive; expose only metadata until a governed review is requested.
3. **Skill candidates** — record legacy skill metadata as inactive candidates; do not copy into the live Skill Factory registry.
4. **Knowledge candidates** — preserve claims/notes for later bounded parsing into proposals; never bulk parse or auto-promote.
5. **Conversation/activity history** — transform selected messages/tool receipts into provenance-bearing historical records, not current conversational context.
6. **Secret quarantine** — hash/report only; do not index, project, or copy into semantic stores.

## Prohibited shortcuts

- no direct attachment of `hermes_hub.db` to current runtime;
- no blind merge into canonical memory;
- no automatic promotion of old beliefs, goals, strategies, or trading conclusions;
- no copying `.obsidian` workspace settings;
- no secret content in generated manifests.

## Next executable gate

The dry-run manifest is complete. `--apply` is authorized only to create an inert archive under `AETHER_HOME\legacy\archives\original-brain`; it performs no semantic migration.
