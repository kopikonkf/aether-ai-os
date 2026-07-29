# Aether Context Continuity Baseline

Status: ACCEPTED DESIGN FOUNDATION, NOT ACTIVE
Date: 2026-07-29

## Current runtime truth

Aether v0.19.2 currently has three separate mechanisms:

1. `SQLiteConversationStore(max_messages=48)` keeps a bounded recent session transcript and deletes older session rows.
2. `AetherMemoryFabric.record_turn()` preserves each user/Aether turn as canonical episodic memory.
3. Lexical retrieval injects up to six relevant memory records into a new model request.

This is bounded history plus retrieval. It is not session compaction, hierarchical compression, or lossless context management.

Legacy `idle_consolidation.py` and related consciousness modules are not composition-root wired and are not counted as active capability.

## Decision

Build an Aether-owned, provider-neutral Context Continuity Engine using dual state:

- Immutable Context Ledger: raw user messages, assistant messages, tool calls, tool results, action receipts, and source metadata.
- Active Context View: system instructions, selected structured checkpoints, protected recent tail, and bounded recall results.

Compaction artifacts are derived views. Raw records remain authoritative and recoverable.

## Required architecture

### 1. Structured checkpoint, not one summary blob

Every checkpoint must preserve explicit fields:

- current objective
- numbered progress state
- accepted decisions
- Founder constraints
- open questions
- blockers and risks
- active files/artifacts and hashes
- action and approval receipts
- unfinished tool calls
- next executable steps
- source message ranges and hashes

### 2. Protected content

Never summarize away:

- Founder messages and corrections
- identity/Northstar/governance instructions
- unresolved actions or approvals
- failed tool calls and failure fingerprints
- exact file paths, IDs, hashes, commands, and test results needed for continuation
- current working set and most recent tail

### 3. Tool-output externalization

Large completed tool outputs are stored outside active context and replaced with typed handles. Handles contain content hash, media/type metadata, source action ID, and retrieval instructions.

Pending, running, failed, or ambiguous tool calls remain visible until resolved.

### 4. Summary DAG and lineage

Checkpoints may summarize raw records or earlier checkpoints. Each node records exact parent IDs and source ranges. A checkpoint can be rebuilt or invalidated without altering raw history.

### 5. Retrieval tools

Planned read-only tools:

- `context_status`
- `context_search`
- `context_expand`
- `context_recent`
- `context_describe`
- `context_doctor`

Expansion is bounded and paginated. The primary interaction loop must not flood itself with full historic payloads.

### 6. Budget policy

Provider adapters expose effective context window and requested output reserve. The engine estimates the complete request, including system prompts and tool schemas.

Initial canary defaults:

- soft threshold: 0.65 of usable input budget
- hard threshold: 0.85 of usable input budget
- protected tail: model-aware token budget, not a fixed message count
- no compaction below soft threshold
- asynchronous compaction between turns at soft threshold
- blocking compaction only at hard threshold or verified provider overflow
- one overflow recovery attempt per model step

Thresholds remain configurable and evidence-driven.

### 7. Guaranteed convergence

Compaction uses escalation:

1. detail-preserving structured checkpoint
2. more aggressive structured checkpoint
3. deterministic bounded fallback that preserves protected fields and references

A compaction is rejected if it does not reduce estimated tokens or if required fields/source lineage are missing.

### 8. Safety and privacy

- redact configured secret patterns before summarization
- raw secret-bearing payloads remain access-controlled
- no summary becomes belief or knowledge automatically
- all compaction operations emit receipts
- manual compaction creates a backup/checkpoint first

## Command surface

- `/compact` and `aether context compact`
- `/context` or `aether context status`
- `/context doctor`
- `/context search <query>`
- `/context expand <handle>`

## Implementation gates

1. Contract and schema tests.
2. SQLite ledger and checkpoint store.
3. Token estimator conformance per provider family.
4. Read-only status/search/expand tools.
5. Manual compaction canary on non-critical session.
6. Automatic soft/hard threshold canary.
7. Telegram, Browser Senses, CLI, and runtime-body continuity tests.
8. Promotion only after measured recall and task-continuation evaluation.
