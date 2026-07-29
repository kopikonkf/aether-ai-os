# ADR-0015 — Governed Knowledge Promotion

**Status:** Accepted in MVP v0.7  
**Date:** 2026-07-28

## Context

Aether needs durable knowledge for cognition, business execution, and Continuous Evolution Engine decisions. Automatic promotion from a repeated statement or a model judgment would allow confidence inflation and contamination of the long-term knowledge base.

## Decision

Knowledge promotion uses an immutable proposal and decision ledger.

The default policy requires:

- at least two supporting canonical records;
- at least two distinct evidence sources;
- no duplicate proposal;
- no unresolved contradiction;
- a trusted principal;
- an explicit decision reason;
- confidence no greater than `0.90`.

Approval appends a `MemoryKind.KNOWLEDGE` record to the canonical memory store. The record includes the proposal ID, proposal hash, evidence snapshots, evidence links, governance identity, reason, and confidence.

Direct `MemoryKind.KNOWLEDGE` writes are rejected unless they carry the governed promotion envelope and trusted governance provenance. Direct `MemoryKind.BELIEF` writes are rejected by the Memory Fabric.

Rejection is terminal. Approval is terminal. Proposal, evidence, and decision tables are protected by SQLite append-only triggers.

## Obsidian

A promoted record may be projected to `05_Knowledge/Aether Curated`. The note is marked `authority: projection_only` and can be rebuilt from canonical storage.

## Failure and concurrency

Promotion is serialized inside one Aether process to prevent simultaneous approve/reject races across the proposal and canonical databases. Multi-node consensus is not implemented in v0.7 and remains a deployment boundary.

## Consequences

- Knowledge is retrievable immediately after promotion because it enters the existing rebuildable retrieval index.
- Knowledge remains distinct from belief, DNA, and Northstar authority.
- The legacy direct promotion method is disabled.
- CEE can later consume promoted knowledge and evidence without trusting raw conversation history.
