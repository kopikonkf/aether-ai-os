# ADR-0005 — Single North Star Authority and Lean Core Layout

**Status:** Implemented  
**Date:** 2026-07-28

## Decision

`aether-core/src/aether/dna/north_star.yaml` is the only North Star authority. The duplicate architecture configuration was deleted.

The executable `aether-core` package no longer contains the historical architecture-document corpus. Project ADRs and research live in top-level `project-docs/`, outside the runtime package.

Markdown retained inside core is limited to identity/runtime assets:

- `src/aether/dna/Genome.md`;
- output templates consumed by ingestion and Obsidian projection.

Architecture prose is not imported or interpreted by runtime code.
