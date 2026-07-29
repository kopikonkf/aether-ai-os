# Current State Inspection — 2026-07-29

## Scope

This inspection separates:

1. **source/build state** — auditable in the working environment;
2. **Founder laptop runtime state** — must be captured from the live Windows host.

## Known live Founder state

Current installed/running baseline: `v0.19.2-founder-alpha-consolidated.1`.

Founder-proven:

- Windows-native Core/Gateway boot;
- 13/13 deterministic first pulse;
- live model cognition;
- Telegram DM conversation;
- authenticated Browser Senses text, camera vision, and browser speech fallback;
- governed write action completed exactly once;
- mutable state resolves to `C:\Users\hp\AppData\Local\Aether`.

## Known consolidated.1 defects / limitations

- successful approval completion may be narrated by a second model generation and desynchronize from disk;
- Telegram approval requires typed commands and has no inline keyboard;
- Telegram command handlers are hardcoded rather than registry-derived;
- Telegram rich presentation adapter is not wired;
- Google TTS is not active;
- Windows persistent services are not implemented;
- Cloudflare ingress, AionUi public health, live nutrition, and conformed runtime body are not accepted.

## Source-state findings

### State authority

Release code is replaceable. Mutable state is rooted at `AETHER_HOME`.

Canonical/rebuildable stores include:

- `sessions/cognitive-sessions.sqlite3`;
- `memory/canonical-episodes.sqlite3`;
- `memory/retrieval-index.sqlite3`;
- `memory/knowledge-proposals.sqlite3`;
- `skills/skill-factory.sqlite3`;
- `obsidian/vault`;
- `governance/pending-actions.sqlite3`;
- `events/action-path.jsonl`;
- `missions/mission-orchestrator.sqlite3`;
- runtime, opportunity, experiment, and evolution ledgers.

### Known storage ambiguity

Both `AETHER_HOME/aether_hub.db` and `AETHER_HOME/db/aether_hub.db` may exist with different authorities. This must be measured before semantic migration or cleanup.

### Legacy continuity

Original `hermes-brain` content has not been semantically imported. Existing migration logic preserves legacy skills, knowledge, Obsidian notes, workspace files, and database bytes as candidates/evidence; it does not silently activate or promote them.

## Working-tree changes staged after inspection began

Not packaged or installed on the Founder laptop:

- signed one-tap Telegram approval callbacks;
- Founder/chat binding and exact-once decision path;
- `Approve once`, `Reject`, and `Details` controls;
- central Telegram command registry;
- generated help and bot command menu;
- boot-time validation that every registered command has a real handler;
- no aspirational `/voice`, `/skills`, `/runtime`, or other dead commands.

Targeted tests: 10 passed.

## Runtime evidence still required

The live Windows host must provide:

- launcher status receipt;
- database existence, sizes, tables, and row counts;
- Obsidian vault note count;
- Skill Registry file count;
- pending approval count and stale records;
- exact AETHER_HOME resolution;
- original `hermes-brain` source path and inventory;
- filesystem size before preservation/freeze.

The current consolidated.1 release already contains `AETHER_STATE_INSPECT.ps1`; no new release is required to capture this evidence.

## Original Source Code Aether brain inventory

The uploaded original backup was inspected directly.

`hermes-brain` contains:

- 155 files;
- approximately 7.7 MB;
- 128 Markdown notes;
- 18 JSON files;
- 3 legacy skill Markdown files;
- one `hermes_hub.db` database.

Selected database counts:

- `agent_activity`: 11,722;
- `tool_calls`: 11,035;
- `messages`: 1,607;
- `agents`: 28;
- `rooms`: 21;
- `meetings`: 5;
- `meeting_messages`: 100.

This is substantive historical operational state, not an empty template.

### Sensitive legacy material

Three potential-secret files were detected by filename and must not enter semantic memory, Obsidian indexes, or a broadly readable archive:

- `credential_pool_template.yaml`;
- `API_Keys_Backup.md`;
- `oc-brain-credential.md`.

The working migration logic now hashes and reports these files but does not copy them. The original bytes remain at the source location until the Founder chooses a separate secret-preservation process.
