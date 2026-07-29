# ADR-0052 — Aether DNA Authority Coherence

- Status: accepted
- Date: 2026-07-30
- Initial hardening issue: #9
- Founder-authorized amendment issue: #11

## Context

Aether has a runtime DNA set under `aether-core/src/aether/dna/` and stable repository contracts at the repository root. These assets are directionally aligned, but authority language previously overlapped when read without an explicit domain hierarchy.

The system must distinguish constitutional direction, machine-readable identity, epistemic invariants, execution governance, interaction style, engineering instructions, memory authority, and dynamic project state. A connector, model, or worker must not resolve contradictions silently.

## Decision

Use **one authority per domain**, not one file for every domain.

### Ultimate amendment authority

The Founder, Dee, is the final authority for accepted constitutional amendments and Founder acceptance. An amendment is not valid merely because a model, runtime, worker, or repository file proposes it.

### Runtime DNA set

1. `aether-core/src/aether/dna/north_star.yaml`
   - sole highest directional, mission, and sacred-principle authority;
   - contains the Founder-approved North Star, milestones, and business portfolio policy;
   - changes require explicit Dee approval.

2. `aether-core/src/aether/dna/Genome.md`
   - epistemic, learning, self-audit, evidence-quality, and evolution invariants;
   - subordinate to the North Star for mission direction;
   - frozen text changes require explicit Dee approval.

3. `aether-core/src/aether/dna/aether.core.json`
   - machine-readable self-model, architecture identity, values, goals, constraints, and runtime rules;
   - subordinate to the North Star and Genome inside their declared domains;
   - does not independently authorize a constitutional amendment or runtime action.

4. `aether-core/src/aether/dna/integrity_manifest.json`
   - Founder-reviewed SHA-256 identity manifest for the three canonical DNA files;
   - proves file identity inside an installed source tree;
   - does not replace Git provenance or Founder review.

### Execution authority

Runtime governance and approval services decide whether a proposal may execute. DNA describes identity, direction, and constraints; it does not auto-authorize side effects.

A proposal must still pass the applicable policy, exact action binding, approval, execution, receipt, and Founder acceptance boundaries.

### Repository contracts and projections

- `SOUL.md` is the human-readable constitutional synthesis for engineering agents and reviewers. It reflects, but does not replace, the runtime DNA set.
- `aether-core/configs/persona.yaml` is the interaction and expression policy loaded for model calls. It is subordinate to DNA and governance.
- `AGENTS.md` is the engineering execution contract. It grants no runtime or constitutional authority.
- `MEMORY.md` maps source, runtime-state, projection, and continuity authorities. It is not autobiographical memory.
- `LASTSTANDINGPOINT.md` is the dynamic cross-session project handoff. It may report current states but cannot amend DNA.
- ADRs explain accepted architecture decisions but cannot override a higher authority.
- MCP, ACP, APIs, plugins, GitHub, Telegram, AionUi, Buzz, Codex, OpenCode, and other workers/connectors never become constitutional or execution authorities merely through access.

## Conflict protocol

When two authority artifacts appear inconsistent:

1. stop automatic mutation, promotion, or destructive execution;
2. preserve exact file paths, hashes, and observed text;
3. classify the conflict domain: directional, constitutional, epistemic, execution, memory, persona, engineering, or documentation;
4. use the authority assigned to that domain for immediate conservative behavior;
5. open a Founder-reviewed issue or pull request;
6. update every dependent integrity hash or contract in the same reviewed amendment;
7. never silently reinterpret a lower-domain file as higher authority.

## Integrity enforcement

`DNALoader` verifies:

- the manifest schema and algorithm;
- exact membership of the canonical DNA set;
- existence and readability;
- YAML/JSON/text parseability as applicable;
- SHA-256 equality for each DNA file.

A failed integrity check prevents `NorthStarAuthority` from initializing. Conservative failure is preferable to running governance against unknown constitutional material.

## Hard governance vetoes

Numeric alignment scoring never overrides:

- an attempted review bypass;
- an irreversible action with neither explicit Founder approval nor an available governed approval path;
- a North Star amendment attempt without both explicit Dee approval and a constitutional-amendment marker.

A normal irreversible action may enter the exact approval path. It must not be auto-approved merely because its numeric alignment score remains above a threshold.

## Founder-approved amendment resolution

On 2026-07-30, Dee explicitly approved resolution of the remaining wording conflicts:

1. `aether.core.json` no longer calls itself the global single source of truth. It now declares itself the machine-readable self-model and constraint projection, subordinate to the North Star and Genome inside their domains.

2. `Genome.md` v1.1 clarifies that “Genome Before Memory” means identity remains recoverable without memory. It no longer says canonical memory should be lost during VPS migration. Governed canonical memory should survive verified, quiescent host migration when available.

3. Broad `belief_update_within_bounds` and `memory_storage` auto-approval entries were removed. Belief promotion, knowledge promotion, canonical-memory writes, and memory-retention policy changes require governance. Candidate creation remains proposal-only.

4. The exact North Star statement remains unchanged in `north_star.yaml`. Human-readable summaries may paraphrase it, but precision-critical evaluation must use the canonical YAML value.

## Consequences

- Every authority artifact has one declared domain.
- DNA tampering is mechanically visible.
- Governance fails closed when DNA integrity cannot be proven.
- Canonical memory migration and identity independence no longer conflict semantically.
- Descriptive self-model constraints cannot bypass runtime governance.
- Future DNA amendments must update the integrity manifest, tests, ADR, and amendment log in the same reviewed change.

## Deferred

- semantic North Star scoring beyond deterministic hard gates;
- signed manifests or hardware-backed attestation;
- automatic constitutional amendment generation.
