# Memory Provider Evaluation — Aether v0.1

## Recommendation

- **Initial episodic provider:** Mnemosyne, isolated behind an Aether adapter.
- **Canonical semantic/belief memory:** Aether-owned SQLite + append-only ledger.
- **Human second brain:** Obsidian projection and curated workspace.
- **Code structural memory:** codebase-memory-mcp.
- **Code semantic editing:** Serena.
- **Scale candidates:** Mem0 and Supermemory through separate adapters.

## Product classification

| Project | Correct role in Aether | Decision |
|---|---|---|
| Mnemosyne | Local episodic/retrieval provider | Default MVP candidate |
| Mem0 | General production memory API | Build optional adapter later |
| Supermemory | Context, profile, document and memory service | Optional scale/hosted-local adapter |
| MemPalace | Verbatim archival conversation memory | Optional evidence/archive provider |
| agentmemory | Coding-agent session memory | Do not use as general default |
| Letta | Stateful agent runtime with memory | Do not place beneath Aether as its canonical memory |
| Khoj | Full second-brain app and autonomous agent | Overlaps UI/runtime stack |
| GitNexus | Code knowledge graph | Excluded from commercial baseline due license |
| Graphify | Generated code/docs knowledge graph | Optional analysis artifact |
| codebase-memory-mcp | Persistent structural code graph | Adopt for internal CEE code lane |
| Serena | LSP-backed code retrieval/editing | Adopt as execution capability, not memory authority |

## Evaluation criteria

The primary criteria were local-first operation, cross-platform viability, provider isolation, exportability, provenance support, temporal semantics, operational complexity, commercial licensing, and fit with Aether's Genome.

Vendor-published benchmarks are useful signals but are not treated as proof until reproduced on Aether workloads.
