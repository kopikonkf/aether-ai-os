# Aether Memory and Continuity Contract

`MEMORY.md` defines where truth and continuity live. It is a stable map, not a running diary.

Dynamic project state belongs in `LASTSTANDINGPOINT.md`. Runtime memories belong in governed `AETHER_HOME` stores. Source history belongs in Git.

## Memory authority map

### GitHub `main`

Authority for:

- source code;
- tests;
- schemas;
- ADRs;
- deployment scripts;
- stable operating contracts;
- accepted documentation.

Git history provides provenance for source changes. It does not contain production runtime state.

### `LASTSTANDINGPOINT.md`

Authority for:

- current phase;
- accepted baseline;
- capability states;
- active blockers;
- canonical execution sequence;
- Founder actions still required;
- cross-session handoff.

Read it at the start of every substantial task. Update it when a milestone, capability state, blocker, or canonical sequence materially changes.

Do not use `MEMORY.md` to duplicate its changing contents.

### `AETHER_HOME`

Authority for governed runtime state, including canonical memory, retrieval projections, approvals, missions, skills, runtime telemetry, and event receipts.

`AETHER_HOME` must remain outside the repository.

A normal source checkout must work without copying production databases into Git.

### Obsidian

Obsidian is a human-readable projection. It can be rebuilt from canonical stores and must not become a competing authority.

### Original brain and legacy archives

Legacy archives are preserved ancestry and project history.

They may contain useful decisions, experiments, documents, skills, and prior state, but they are not automatically:

- current autobiographical memory;
- accepted beliefs;
- active skills;
- canonical knowledge;
- runtime database authority.

Legacy material enters current Aether only through explicit review, provenance, normalization, governance, and promotion.

### Chat and agent sessions

ChatGPT, Codex, OpenCode, Telegram, ACP, MCP, Buzz, and other sessions are working context surfaces.

Their messages and outputs are not automatically canonical memory. Important outcomes must be converted into one or more of:

- source changes;
- issue or PR records;
- ADRs;
- `LASTSTANDINGPOINT.md` updates;
- governed runtime memory records;
- action or conformance receipts.

## Required continuity read order

For a new agent or session:

1. `SOUL.md` — constitutional identity and invariants
2. `AGENTS.md` — execution protocol and authority hierarchy
3. `MEMORY.md` — authority map and continuity rules
4. `LASTSTANDINGPOINT.md` — current dynamic state
5. relevant issue, ADR, tests, and receipts

A session that has not read these documents must not claim full project context.

## What should be remembered

Preserve information when it changes future decisions or prevents repeated work, including:

- Founder-approved architecture decisions;
- accepted capability boundaries;
- migration and rollback decisions;
- provider or runtime conformance evidence;
- security incidents and mitigations;
- known platform-specific failure modes;
- exact release and state-migration receipts;
- product hypotheses, experiment results, and kill conditions;
- unresolved blockers and next actions.

Prefer structured records with:

- source;
- observed time;
- correlation or issue identifier;
- evidence links;
- content hash where useful;
- authority classification;
- retention or review policy.

## What must not become canonical memory automatically

Do not promote automatically:

- hidden chain-of-thought;
- speculative internal reasoning;
- raw provider prompts;
- temporary debugging chatter;
- unverified model claims;
- complete external chat histories;
- Buzz room history;
- browser pages without provenance;
- credentials or secret-bearing configuration;
- legacy databases or notes in bulk;
- personal data unrelated to the mission;
- generated summaries that cannot point to sources.

Preserve observable messages, decisions, tool/action receipts, outputs, and concise rationale summaries instead of private reasoning traces.

## Memory write rules

### Episodic memory

May record bounded interaction and action history with channel, session, provider, correlation, and receipt references.

### Knowledge memory

Must enter through the knowledge promotion path. Direct knowledge writes are forbidden when governance is required.

### Beliefs

Must not be written as ordinary memory records. Belief changes require their dedicated governed process.

### Action memory

Must bind to the exact approval/action identifier and result receipt.

### External events

External events are evidence inputs, not automatic internal truth. Store provenance and classify trust before promotion.

## Retrieval rules

Retrieval must be:

- bounded by namespace, kind, score, and result count;
- explicit about source and provider;
- safe against secret leakage;
- distinguishable from canonical storage;
- rebuildable from canonical records;
- honest when no relevant result exists.

A retrieval hit is context, not final authority.

## Context continuity direction

The accepted future Context Continuity Engine consists of:

- an immutable observable context ledger;
- structured checkpoints;
- a protected recent-message tail;
- externalized large tool outputs with typed recall handles;
- a summary DAG with source lineage;
- soft and hard token thresholds;
- deterministic convergence fallback;
- bounded search, expand, and doctor commands.

Do not preserve hidden chain-of-thought. Preserve user-visible conversation, decisions, receipts, results, and rationale summaries.

Do not activate automatic compaction before canary evaluation proves recall quality and continuity safety.

## Cross-session handoff protocol

Update `LASTSTANDINGPOINT.md` when any of the following changes:

- accepted release;
- current source authority;
- capability state progression;
- VPS or production topology;
- migration authority or state count;
- canonical execution order;
- major blocker;
- Founder acceptance;
- deferred project activation.

A good handoff states:

```text
what is accepted
what is implemented but not installed
what is conformed but not active
what is waiting for Founder proof
what must happen next
what must not be done
where the authoritative evidence lives
```

Avoid embedding volatile branch heads as “current” facts when the document change itself will create a newer commit. Prefer historical wording such as “PR #4 merge commit was …” or omit the SHA when it is not operationally necessary.

## Repository working memory

The repository may contain stable context files:

```text
SOUL.md
AGENTS.md
MEMORY.md
LASTSTANDINGPOINT.md
project-docs/architecture/ADR-*.md
project-docs/foundations/*.md
project-docs/testing/*.md
```

Their roles are different:

- `SOUL.md`: constitutional identity
- `AGENTS.md`: execution contract
- `MEMORY.md`: authority and continuity map
- `LASTSTANDINGPOINT.md`: dynamic current state
- ADRs: durable architecture decisions
- foundation docs: accepted design baselines
- testing docs: executable proof procedures and receipts

Do not collapse them into one giant prompt file.

## Stable anchors

The following are stable anchors as of the current development line, but current status must still be verified in `LASTSTANDINGPOINT.md`:

- Founder-accepted laptop release: `v0.19.2-founder-alpha-frozen.2`;
- GitHub `main` is source authority;
- original brain continuity is preservation plus governed curation, not bulk merge;
- AETHER_HOME is separate runtime-state authority;
- Aether Operational MCP is read-only by default;
- Windows VPS conformance precedes public ingress;
- Founder Acceptance precedes MVP v0.20 shipping;
- Buzz multi-agent and huddle work follows one-room, one-worker, signed-loop proof.

## Memory hygiene

Do not append every session summary to this file.

Do not store secrets, tokens, account identifiers, private addresses, or raw production logs here.

Do not silently rewrite history. Correct inaccurate records through a reviewed commit and preserve the reason in the issue or PR.

When uncertain, retain the evidence, classify it as unverified, and avoid promoting it into canonical memory.