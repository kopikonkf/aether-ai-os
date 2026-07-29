# ADR-0052 — Aether DNA Authority Coherence

- Status: proposed for Founder review
- Date: 2026-07-30
- Issue: #9

## Context

Aether already has a runtime DNA set under `aether-core/src/aether/dna/` and stable repository contracts at the repository root. These assets are directionally aligned, but several files use authority language that can appear overlapping when read without an explicit hierarchy.

The system must distinguish constitutional direction, machine-readable identity, epistemic invariants, interaction style, engineering instructions, memory authority, and dynamic project state. A connector, model, or worker must not resolve contradictions silently.

## Decision

Use the following authority map.

### Ultimate amendment authority

The Founder, Dee, is the final authority for accepted constitutional amendments. An amendment is not valid merely because a model, runtime, worker, or repository file proposes it.

### Runtime DNA set

1. `aether-core/src/aether/dna/north_star.yaml`
   - sole highest directional and mission authority;
   - contains the Founder-approved North Star, sacred principles, milestones, and business portfolio policy;
   - changes require explicit Dee approval.

2. `aether-core/src/aether/dna/aether.core.json`
   - machine-readable self-model, architecture identity, values, goals, constraints, and runtime rules;
   - subordinate to `north_star.yaml` when directional language conflicts;
   - does not independently authorize a North Star amendment.

3. `aether-core/src/aether/dna/Genome.md`
   - epistemic, learning, self-audit, and evidence-quality invariants;
   - subordinate to the North Star for mission direction;
   - frozen text changes require explicit Dee review.

4. `aether-core/src/aether/dna/integrity_manifest.json`
   - Founder-reviewed SHA-256 integrity manifest for the three canonical DNA files;
   - proves file identity inside an installed source tree;
   - does not replace Git provenance or Founder review.

### Repository contracts and projections

- `SOUL.md` is the human-readable constitutional synthesis for engineering agents and reviewers. It must reflect, not replace, the runtime DNA set.
- `aether-core/configs/persona.yaml` is the interaction and expression policy loaded for model calls. It is subordinate to DNA and governance.
- `AGENTS.md` is the engineering execution contract. It grants no runtime or constitutional authority.
- `MEMORY.md` maps source, runtime-state, projection, and continuity authorities. It is not autobiographical memory.
- `LASTSTANDINGPOINT.md` is the dynamic cross-session project handoff. It may report current states but cannot amend DNA.
- ADRs explain accepted architecture decisions but cannot override a higher authority.

## Conflict protocol

When two authority artifacts appear inconsistent:

1. stop automatic mutation or promotion;
2. preserve exact file paths, hashes, and observed text;
3. classify whether the conflict is directional, constitutional, operational, persona-only, or documentation-only;
4. prefer the higher authority for immediate safe behavior;
5. open a Founder-reviewed issue or pull request;
6. do not silently rewrite frozen DNA or reinterpret it as permission.

## Integrity enforcement

`DNALoader` must verify:

- the manifest schema and algorithm;
- exact membership of the canonical DNA set;
- existence and readability;
- YAML/JSON/text parseability as applicable;
- SHA-256 equality for each DNA file.

A failed integrity check prevents `NorthStarAuthority` from initializing. Conservative failure is preferable to running governance against unknown constitutional material.

## Hard governance vetoes

Numeric alignment scoring must never override:

- an attempted review bypass;
- an irreversible action with neither explicit Founder approval nor an available governed approval path;
- a North Star amendment attempt without both explicit Dee approval and a constitutional-amendment marker.

A normal irreversible action may enter the exact approval path. It must not be auto-approved merely because its numeric alignment score remains above a threshold.

## Observed frozen-text discrepancies

This ADR records, but does not amend, the following:

1. `aether.core.json` describes itself as a single source of truth for identity and constitutional constraints, while `north_star.yaml` declares itself the sole highest authority. Operational interpretation: the JSON is the machine self-model within the DNA set; the North Star remains higher for direction. Wording amendment requires Founder review.

2. `Genome.md` states that the genome survives the VPS and memory does not. Current production architecture intentionally migrates canonical `AETHER_HOME` memory to the VPS. Operational interpretation: identity must remain recoverable without memory, not that canonical memory should be discarded. Wording amendment requires Founder review.

3. `aether.core.json` lists bounded belief updates and memory storage as auto-approvable, while current governed memory code forbids ordinary belief writes and requires promotion for governed knowledge. Runtime code and current governance remain authoritative for execution until the frozen self-model is amended explicitly.

4. `SOUL.md` contains a compatible human-readable North Star synthesis, but the exact canonical statement remains the YAML value and should be quoted from that file when precision matters.

## Consequences

- DNA tampering becomes mechanically visible.
- Governance fails closed when DNA integrity cannot be proven.
- Workers receive a clear authority map.
- Existing frozen DNA text is preserved pending explicit Founder amendment.
- Future DNA changes require updating the integrity manifest in the same reviewed change.

## Deferred

- semantic North Star scoring beyond deterministic hard gates;
- signed manifests or hardware-backed attestation;
- automatic constitutional amendment generation;
- changes to the frozen North Star, Genome, or machine self-model text.
