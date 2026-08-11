# Aether Principal Runtime Profiles v0.1

- Status: Proposed implementation contract
- Date: 2026-08-11
- Related: ADR-0055, ADR-0056, APCB v0.1 contract, Mission Orchestrator
- Scope: multi-principal execution through Herdr without direct principal-to-principal chat

## 1. Purpose

Aether treats SOTA models as replaceable Principal Minds that generate architecture, code, research, verification, and adversarial analysis. Herdr is the local execution fabric for terminal-backed agents. Aether remains the canonical authority and shared memory.

The operating rule is:

```text
Principal identity -> Aether mission/work -> APCB -> Herdr -> agent runtime
                                                   |
                                                   v
                                             execution evidence
                                                   |
                                                   v
                                              Aether state
```

A principal may reason independently, but it must publish durable handoff artifacts to Aether. Direct principal-to-principal messaging is not part of the coordination protocol.

## 2. Principal vs runtime

These are deliberately different concepts.

- **Principal** = cognitive role, identity, capability profile, and attribution in Aether.
- **Runtime** = process/harness used to execute work locally.
- **Herdr** = terminal/process/session fabric for local runtimes.
- **APCB** = deterministic adapter between Aether work state and Herdr execution.

A model provider never receives authority merely because it is mapped to a principal profile.

## 3. Principal profiles

### ChatGPT — systems integration principal

Primary role:
- cross-subsystem architecture synthesis;
- integration planning;
- verification strategy;
- final technical synthesis for work that spans multiple Aether subsystems.

Preferred execution:
- ChatGPT/Codex host through Aether MCP when the model is remote;
- Codex runtime through Herdr when code execution is required on the VPS.

Typical work:
- translate accepted ADRs into implementation slices;
- inspect runtime evidence;
- review integration boundaries;
- coordinate remediation work after verification failures.

Do not use ChatGPT identity as an unconditional constitutional authority. Founder/Aether governance remains authoritative.

### Claude — architecture principal

Primary role:
- architecture design;
- ADR drafting;
- invariants and boundary analysis;
- independent design review.

Preferred execution:
- Claude Code through Herdr for repository implementation;
- Claude remote host through Aether MCP for review/proposal work.

Typical work:
- inspect architecture before coding;
- produce proposed ADRs;
- review other principal artifacts;
- identify governance or abstraction leaks.

Acceptance rule:
- architecture artifacts are proposals until accepted by Aether governance.

### Gemini — research and evidence principal

Primary role:
- external research;
- standards/API comparison;
- multimodal or documentation analysis;
- evidence gathering and contradiction finding.

Preferred execution:
- Gemini CLI through Herdr where available;
- otherwise remote Gemini host through Aether MCP.

Typical work:
- investigate current framework/provider behavior;
- produce evidence bundles;
- compare implementation alternatives;
- identify stale assumptions in existing ADRs.

Acceptance rule:
- external findings enter Aether as evidence with source, timestamp, stance, and provenance.

### Qwen — implementation principal

Primary role:
- code generation;
- refactoring;
- tests;
- mechanical integration work.

Preferred execution:
- Qwen-compatible CLI/runtime through Herdr;
- OpenCode/Kilo/Codex-compatible execution only when explicitly bound to the Qwen principal profile.

Typical work:
- implement an accepted ADR slice;
- add regression/security tests;
- execute bounded verification;
- produce patch/artifact and receipt metadata.

Acceptance rule:
- implementation work must reference its Aether work item and acceptance criteria.

### Kimi — adversarial verification principal

Primary role:
- red-team analysis;
- failure injection;
- race/edge-case discovery;
- security and recovery review.

Preferred execution:
- Kimi Code CLI through Herdr.

Typical work:
- attack a newly implemented feature;
- deliberately trigger expected failures;
- challenge optimistic assumptions;
- verify rollback and recovery behavior.

Acceptance rule:
- findings become Aether evidence or remediation work items, not direct runtime mutations.

### DeepSeek — alternative reasoning / optimization principal

Primary role:
- alternative architecture proposals;
- simplification;
- algorithmic/implementation optimization;
- second-opinion review.

Preferred execution:
- DeepSeek-compatible local CLI through Herdr when available;
- otherwise remote MCP principal.

Typical work:
- challenge over-engineered designs;
- propose lower-complexity alternatives;
- analyze performance/cost tradeoffs.

Acceptance rule:
- alternative proposals are compared against existing North Star, Genome, evidence, and reversibility constraints.

### OpenCode — integration runtime coordinator

OpenCode is treated primarily as a **runtime/integration control plane**, not as a sovereign Principal.

Responsibilities:
- observe Aether runtime state locally;
- run or host compatible coding workers;
- expose worker state to APCB/Herdr;
- perform bounded integration tasks assigned by Aether.

OpenCode may operate workers such as Claude CLI, Cline, Codex, Kilo CLI, and compatible agents. A worker does not inherit OpenCode authority. Each worker is attributed to the Aether principal identity explicitly selected for the Aether work item.

## 4. Standard work lifecycle

Every principal follows the same lifecycle:

```text
AETHER READY
    |
    v
CLAIM
    |
    v
CONTEXT
    |
    v
EXECUTE
    |
    +--> BLOCKED -> report evidence -> Aether creates follow-up
    |
    v
VERIFY
    |
    v
PUBLISH ARTIFACTS
    |
    v
HANDOFF
    |
    v
AETHER REVIEW / NEXT WORK
```

A principal never treats the Herdr pane state as the source of mission truth.

## 5. Canonical context envelope

APCB gives every local principal a bounded context package derived from Aether state:

```yaml
context:
  mission_id: MISSION-...
  work_id: WORK-...
  principal_id: qwen
  objective: "..."
  northstar_constraints: []
  genome_constraints: []
  accepted_decisions: []
  relevant_adrs: []
  evidence: []
  acceptance_criteria: []
  workspace_id: WS-...
  expected_inputs: []
  forbidden_actions: []
  verification_requirements: []
  correlation_id: ...
```

The package is intentionally smaller than the source principal's conversation history.

## 6. Standard handoff envelope

When a principal finishes or blocks work, APCB converts the runtime result into an Aether artifact:

```yaml
handoff:
  type: principal_handoff
  from_principal: claude
  to_principal: qwen
  mission_id: MISSION-...
  work_id: WORK-...
  summary: "..."
  decisions: []
  artifacts: []
  evidence: []
  verification: []
  open_questions: []
  blockers: []
  recommended_next_work: []
  correlation_id: ...
```

The receiving principal retrieves the handoff through Aether MCP. It does not receive the sender's hidden prompt transcript.

## 7. Herdr topology

For one mission, use a dedicated Herdr workspace and isolated worktrees/panes.

Recommended topology:

```text
AETHER MISSION workspace
|
+-- architecture/claude
+-- research/gemini
+-- implementation/qwen
+-- adversarial/kimi
+-- alternative/deepseek
+-- integration/opencode
+-- verification/codex
```

Use separate worktrees for concurrent writers touching the same repository. A principal may inspect another worktree through Aether artifacts, but should not directly edit another principal's worktree unless the Aether work item explicitly assigns that responsibility.

## 8. Dispatch rules

APCB dispatches only work items whose:

- principal profile exists;
- required capabilities are satisfied;
- workspace binding is valid;
- dependencies are complete;
- Aether mission state permits execution;
- governance has not blocked the action.

Dispatch idempotency key:

```text
(work_id, attempt_number, principal_id)
```

Agent restart must reconcile the existing attempt before creating another dispatch.

## 9. Review lanes

Aether may assign different work lanes to different principals:

```text
ARCHITECTURE
  Claude -> ChatGPT review

RESEARCH
  Gemini -> ChatGPT/Claude synthesis

IMPLEMENTATION
  Qwen -> Codex/ChatGPT verification

ADVERSARIAL
  Kimi -> remediation principal

OPTIMIZATION
  DeepSeek -> architecture comparison

INTEGRATION
  OpenCode/Codex -> runtime assembly
```

No lane is automatically superior to another. Aether uses North Star alignment, evidence quality, risk, reversibility, and verification results when synthesizing outcomes.

## 10. What each principal must publish

Claude:
- ADR/proposal;
- architecture invariants;
- unresolved questions.

Gemini:
- evidence records;
- source references;
- contradiction findings;
- freshness.

Qwen:
- diff/artifacts;
- tests;
- verification receipt;
- implementation notes.

Kimi:
- adversarial findings;
- reproduced failures;
- severity;
- remediation recommendation.

DeepSeek:
- alternative design;
- complexity/performance analysis;
- tradeoff matrix.

ChatGPT:
- integration synthesis;
- cross-subsystem review;
- final implementation/verification recommendation.

OpenCode/Herdr:
- runtime/session evidence;
- dispatch state;
- process/worker health;
- recovery evidence.

## 11. Approval boundary

No principal profile, Herdr state, MCP token, or OpenCode worker status constitutes Founder approval.

Mutation must continue to pass the existing Aether governance chain. Principal coordination only determines **who does the work and what context they receive**; it does not redefine **who is authorized to approve the work**.

## 12. Founder interaction

Founder is removed from routine handoff traffic.

Founder remains involved when:

- policy requires human approval;
- North Star/Genome interpretation is ambiguous;
- a high-risk or irreversible decision requires escalation;
- principal disagreement cannot be resolved from evidence;
- Aether governance explicitly requires Founder intervention.

Routine flow should therefore be:

```text
Founder -> Mission
Aether -> Work allocation
APCB -> Herdr execution
Principals -> artifacts/evidence
Aether -> verification/governance
Founder -> only required approvals/constitutional decisions
```

## 13. MVP proof

The first Founder-proven scenario should use three heterogeneous roles:

1. Claude creates an architecture proposal.
2. Gemini validates external evidence and records contradictions.
3. Qwen implements the accepted slice in an isolated worktree.
4. Kimi attacks the implementation.
5. Codex/OpenCode performs integration verification.
6. Aether records all artifacts and creates remediation work if Kimi finds a defect.
7. Founder is never asked to manually copy context between principals.

Success means the same mission can move across principals using only Aether canonical state and Herdr execution references.
