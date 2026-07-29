# ADR-0002 — Aether Memory Fabric

**Status:** Accepted for implementation after Sense Event Path baseline  
**Decision date:** 2026-07-27  
**Authority:** Aether Architecture Protocol v0.1

## Decision

Aether will not adopt a single product as "the memory." Memory is a fabric of independently replaceable layers.

1. **Constitutional memory** remains in Aether DNA and is never writable by a provider.
2. **Working memory** is session-local and disposable.
3. **Episodic memory** uses a provider adapter. The initial default is Mnemosyne through its generic SDK/MCP surface, with all storage paths redirected into `AETHER_MEMORY_DIR`.
4. **Semantic and belief memory** remains Aether-owned. Conversation text cannot directly become a belief. Promotion requires provenance, evidence, lifecycle state, and governance.
5. **Obsidian** is the human-readable second brain and curated workspace. It is a projection, not the machine authority.
6. **Code intelligence** is a separate capability. `codebase-memory-mcp` provides the structural graph; Serena provides symbol-aware retrieval and editing. Neither is treated as autobiographical or belief memory.

## Why Mnemosyne is the initial episodic provider

The choice is based on architecture rather than vendor benchmark claims:

- local-first single-file SQLite;
- direct Python API plus MCP;
- working, episodic, temporal, and graph-oriented primitives;
- export/import and optional sync;
- low operational overhead for an MVP;
- easy containment behind `MemoryProvider`.

Aether must not use the provider's legacy default home directory or runtime-specific plugin. The adapter identity is `aether.memory.mnemosyne`; the provider is an implementation detail.

## Why not make Obsidian the primary database

Markdown is durable, inspectable, versionable, and excellent for human cognition. It is poor as the sole transactional memory engine because concurrency, lifecycle transitions, temporal supersession, deduplication, query ranking, and atomic updates are difficult to guarantee. Obsidian receives curated projections and can emit proposed changes, but those changes pass through ingestion and governance.

## Memory authority invariant

A provider may lose all indexes and Aether must still retain identity and be able to reconstruct governed memory from DNA, event records, ledger entries, repository history, and exports.

## Required contract evolution

The current `MemoryRecord(key, value, namespace, metadata)` contract is too weak. The next memory-focused implementation must add:

- memory type;
- stable record ID;
- subject and scope;
- provenance and evidence links;
- confidence and importance;
- valid-time and transaction-time fields;
- supersession links;
- policy classification;
- content hash;
- export/import, health, delete/forget, and replay operations.

## Existing defect to remove

The runtime-host memory plugin currently maps operational notes into `believe(...)`. This conflates episodes with beliefs and violates the Genome. Operational writes must instead emit episodic memory events; belief promotion must remain a separate governed lifecycle.

## Consequences

- Memory remains provider agnostic.
- Aether can start locally and replace the provider later.
- Obsidian remains useful without becoming an unsafe source of truth.
- Code intelligence can evolve independently from personal and organizational memory.
- CEE can rely on traceable incidents and decisions rather than opaque vector recall.
