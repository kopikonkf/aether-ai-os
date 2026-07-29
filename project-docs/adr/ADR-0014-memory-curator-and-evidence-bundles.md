# ADR-0014 — Memory Curator and Evidence Bundles

**Status:** Accepted in MVP v0.7  
**Date:** 2026-07-28

## Context

Aether v0.6 could preserve episodes and retrieve them before cognition, but it did not define how repeated experience becomes durable knowledge. The legacy `KnowledgeLifecycle` could promote claims using calculated “gravity” without requiring canonical evidence, source diversity, contradiction checks, or a trusted decision.

That path violated the Bootstrap and Genome distinction between storage, observation, knowledge, and belief.

## Decision

Aether introduces an evidence-first `MemoryCurator` with these stages:

1. Read only canonical records.
2. Accept automatic candidates only when a canonical record contains explicit `knowledge_candidate` metadata.
3. Snapshot evidence identifiers, content hashes, source, observed time, session, correlation, and excerpt.
4. Group candidates into immutable knowledge proposals.
5. Detect exact or near duplicates.
6. Detect opposite-polarity proposals sharing the same semantic claim key.
7. Preserve contradictions visibly.
8. Submit proposals to trusted governance.

Casual conversation records are never candidates by default. The standard turn recorder does not copy arbitrary candidate metadata from user input.

## Consequences

- A background curator may propose knowledge but cannot approve it.
- Candidate extraction is intentionally conservative and deterministic in v0.7.
- Semantic contradiction detection depends on a stable `claim_key` and polarity; richer model-assisted analysis can be added later as advisory evidence.
- Every proposal is auditable back to canonical records.
- Duplicate and contradiction state cannot be silently discarded.
