# ADR-0013 — Memory Fabric Activation

**Status:** Accepted in MVP v0.6

## Decision

Activate Memory Fabric with three distinct authorities:

1. **Canonical episodic store:** append-only Aether SQLite records.
2. **Retrieval provider:** rebuildable lexical SQLite projection.
3. **Obsidian:** explicit human-readable session digest projection.

External providers such as Mnemosyne, Mem0, or Supermemory remain optional
adapters. They are not required to boot v0.6 and may never own Aether identity,
constitution, belief lifecycle, or canonical history.

## Retrieval rule

Relevant memory is retrieved before model invocation and injected with record
ID, content hash, source, timestamp, and session provenance. Retrieved memory is
evidence, not immutable truth.

## Failure rule

Memory read/write/index/projection failures are surfaced in response metadata
and events but do not block cognition.

## Rebuild rule

The retrieval index and Obsidian projection may be deleted and rebuilt from the
canonical store. Provider-specific identifiers are forbidden in Core events.
