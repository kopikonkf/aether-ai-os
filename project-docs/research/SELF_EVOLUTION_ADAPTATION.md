# Self-Evolution Reference Adaptation

## Adopt

- Treat evolution as an external/offline pipeline operating on versioned targets.
- Mine real execution traces and failures into evaluation cases.
- Separate train, validation, and holdout data.
- Generate multiple candidates through a replaceable optimizer.
- Enforce hard constraints before scoring.
- Compare baseline and candidate on held-out evidence.
- Preserve Git/artifact lineage and rollback.
- Promote only through governance.

## Do not copy as-is

- Runtime-specific repository paths or namespaces.
- Skill-only scope.
- LLM-as-judge as the sole acceptance signal.
- Keyword-overlap fitness as proof of improvement.
- Proceeding when the baseline violates hard constraints.
- Assuming a CLI flag means tests were actually executed.
- Direct deployment from optimizer output.

## Aether extension

The same optimizer contract may target internal skills, prompts, tools, code, workflows, and architecture, plus external business playbooks, offers, acquisition processes, delivery processes, and unit economics. Candidate generation is never authority; Aether governance and external evidence decide promotion.

## Curator mechanics retained

- usage telemetry and explicit lifecycle states;
- scheduled review only after an idle gate;
- dry-run reports;
- pre-mutation snapshots;
- archive and restore instead of automatic deletion;
- pinning and provenance-aware protection;
- review worker isolated from the main conversation context.

Aether adds hard capability boundaries: the review worker receives only memory-read, skill-read, and candidate-write ports. It is not given arbitrary shell or production filesystem access. Prompt instructions are not treated as security controls.
