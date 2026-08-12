# ADR-0056 — Principal Coordination Plane: Herdr Runtime Bridge

- Status: Proposed for implementation
- Date: 2026-08-11
- Decision owner: Founder / Aether architecture
- Related: ADR-0008 (Governed Action Path), ADR-0010 (Trusted Approval Inbox), ADR-0034 (Mission Orchestrator), ADR-0051 (MCP Capability Plane Baseline), ADR-0055 (Principal Coordination Plane)

## Context

Aether needs to coordinate multiple independent AI principals such as Claude, ChatGPT/Codex, Gemini, Qwen, Kimi, and DeepSeek without making the Founder a manual message router.

Aether already owns durable mission, evidence, decision, approval, runtime, and receipt state. ADR-0055 correctly establishes that principals must communicate through Aether-owned canonical state rather than an unrestricted principal-to-principal chat bus.

Herdr provides a complementary capability on the host: it runs multiple coding agents in persistent terminal panes, tracks agent state, exposes agent/pane/workspace automation, and provides a local socket API for scripts and other agents. Herdr also supports several relevant coding agents, including Claude Code, Codex, Kimi Code CLI, and detected Gemini CLI, with direct automation primitives for starting agents, prompting them, waiting for state, reading output, and managing panes. Herdr is therefore a suitable **execution/fleet layer**, but it must not become Aether's canonical mission, governance, or decision authority.

## Decision

Build a small **Aether Principal Coordination Bridge (APCB)** that connects Aether's canonical coordination state to Herdr's local agent orchestration surface.

The bridge is not a new AI-to-AI protocol and is not a second governance engine. It is a deterministic adapter with four responsibilities:

1. Read eligible Aether work items / mission steps.
2. Map them to an authorized principal and a Herdr-managed agent session.
3. Launch/prompt/observe the agent through Herdr.
4. Convert agent completion, blockage, artifacts, and failures back into Aether-owned work/evidence state.

The communication model is:

```text
Aether canonical state
    │
    │ claim / dispatch
    ▼
APCB (Aether Principal Coordination Bridge)
    │
    │ local socket / CLI
    ▼
Herdr
    │
    ├── Claude Code
    ├── Codex
    ├── Kimi Code
    ├── Qwen / compatible CLI
    ├── Gemini CLI
    └── other managed agents
    │
    │ result / blocked / artifact / state
    ▼
APCB
    │
    ▼
Aether canonical state
```

## Why Herdr is not the source of truth

Herdr is excellent at process/session orchestration: panes, agent lifecycle, logs, prompts, waits, and local handoff. Aether is responsible for identity, mission, governance, evidence, approvals, and durable architectural decisions.

Therefore:

- Herdr state is operational telemetry, not canonical mission state.
- Aether work ownership is authoritative even if Herdr reports a pane as active.
- Herdr may restart/recover an agent process, but it must not invent or reassign Aether mission ownership.
- Agent output is evidence until promoted into an Aether decision or artifact.

## Principal identity

Each managed principal receives an Aether identity:

```yaml
principal:
  id: claude
  role: architecture_principal
  capabilities:
    - architecture_review
    - design
    - diagnostic
  mutation_authority: false
  execution_profiles:
    - herdr:claude
```

The bridge maps `principal_id` to an execution profile, not directly to an arbitrary shell command.

Example profiles:

```yaml
execution_profiles:
  herdr:claude:
    herdr_kind: claude
    prompt_mode: task
  herdr:codex:
    herdr_kind: codex
    prompt_mode: task
  herdr:kimi:
    herdr_kind: kimi
    prompt_mode: task
```

Provider/model identity is never itself an authorization grant.

## Coordination protocol

The APCB uses Aether-owned work items as the durable handoff protocol.

A dispatchable work item must contain at least:

```json
{
  "work_id": "WORK-...",
  "mission_id": "MISSION-...",
  "principal_id": "qwen",
  "attempt": 1,
  "state": "ready",
  "objective": "...",
  "constraints": ["..."],
  "required_capabilities": ["implementation", "verification"],
  "workspace_id": "...",
  "correlation_id": "..."
}
```

Dispatch is idempotent. A work item is never duplicated merely because an agent process restarts.

The bridge should maintain a local execution receipt containing:

```text
work_id
principal_id
herdr_workspace_id
herdr_tab_id
herdr_pane_id
agent_session_reference (when available)
started_at
completed_at
last_state
attempt
correlation_id
```

This receipt is a bridge/runtime artifact, not a replacement for Aether's canonical work state.

## State machine

The bridge maps Aether work states to Herdr operational states without making them identical:

```text
Aether:
READY -> CLAIMED -> DISPATCHED -> RUNNING -> REVIEW -> COMPLETED
                                  │
                                  ├-> BLOCKED
                                  └-> FAILED

Herdr:
idle / working / blocked / exited / pane unavailable
```

Only Aether changes the canonical work state.

Herdr state may trigger an observation/reconciliation event, but must not directly mutate mission state without passing through Aether services.

## Handoff protocol

Agent-to-agent handoff is represented as a new Aether artifact, not as direct pane-to-pane messaging:

```json
{
  "type": "principal_handoff",
  "from_principal": "claude",
  "to_principal": "qwen",
  "work_id": "WORK-...",
  "summary": "...",
  "decisions": ["DEC-..."],
  "artifacts": ["ART-..."],
  "verification": ["VR-..."],
  "open_questions": ["..."],
  "correlation_id": "..."
}
```

The receiving principal retrieves this through Aether MCP. No principal needs to know how another principal is hosted.

## Herdr integration boundary

The bridge should use the highest-level Herdr interface that is sufficient:

1. CLI wrappers for ordinary automation;
2. local socket API for long-lived coordination and subscriptions;
3. raw terminal/pane control only when a supported agent integration cannot provide the required primitive.

Use Herdr's agent abstractions for:

- start;
- prompt;
- wait;
- read;
- blocked detection;
- session recovery;
- neighboring-agent inspection;
- workspace/pane lifecycle.

Do not embed Herdr-specific state into Aether contracts beyond execution-reference metadata.

## Model/provider independence

Aether must not depend on a provider-specific GitHub connector or platform connector to coordinate principals.

Every principal should reach the same Aether capability plane through its native host, typically:

```text
AI host -> Aether MCP -> Aether
```

Herdr is only needed when the principal is executed as a local coding agent on the Aether host or an attached development machine.

This creates two complementary paths:

```text
Remote-capable principal:
AI host -> remote Aether MCP -> Aether

Local coding principal:
AI host/process -> Herdr -> APCB -> Aether state + MCP
```

## No direct multi-model bus

Aether will not implement a generic message broker for model-to-model conversation in this phase.

This avoids:

- prompt fan-out;
- duplicate context stores;
- inconsistent authority;
- uncontrolled agent loops;
- hidden side channels;
- provider-specific coupling.

Aether-owned work, decision, evidence, and receipt records are the coordination substrate.

## Human approval boundary

Mutation remains governed by existing Aether policy.

The bridge MUST NOT:

- synthesize terminal Founder approvals;
- treat a Herdr prompt as an approval;
- elevate a principal because Herdr reports it as working;
- reuse the Living Machine MCP operator credential as principal identity;
- bypass `ActionGovernor`, `GovernedActionPath`, or the Trusted Approval Inbox.

## Failure and recovery

The bridge must tolerate:

- agent process exit;
- Herdr restart;
- network disconnect between bridge and Aether;
- stale work claim;
- duplicate dispatch;
- agent blocked state;
- verification failure;
- workspace disappearance;
- concurrent edits;
- principal unavailable.

Recovery rules:

1. Reconcile Herdr state before redispatching.
2. Reuse the same `work_id` with incremented attempt number; never create an accidental duplicate mission step.
3. Record failure/blocked evidence before retry.
4. Require optimistic concurrency on work state transitions.
5. Never silently reassign a claimed work item.
6. Preserve all attempts as auditable evidence.

## Initial implementation scope

The first implementation should be intentionally small:

### APCB service

- `poll_ready_work()`
- `claim_work(work_id, principal_id)`
- `dispatch_work(work_id)`
- `observe_work(work_id)`
- `reconcile_work(work_id)`
- `complete_work(work_id, result)`
- `block_work(work_id, reason)`
- `fail_work(work_id, reason)`

### Herdr adapter

- `ensure_workspace()`
- `ensure_agent()`
- `prompt_agent()`
- `wait_agent()`
- `read_agent()`
- `agent_state()`
- `recover_agent()`

### Aether artifacts

Use existing canonical contracts wherever possible. Add only bridge metadata required to correlate Aether work with Herdr execution.

## Security

The bridge is local-first.

- Herdr socket remains local to the host.
- The bridge authenticates to Aether with a dedicated service identity, not a model API key.
- Principal identity is explicit and auditable.
- The bridge has no authority to approve governed actions.
- Agent prompts never contain raw credentials.
- Results are redacted/classified before being promoted to canonical evidence.

## Acceptance criteria

The bridge is Founder-proven when all of the following are demonstrated with at least two heterogeneous principals:

1. Aether creates one work item.
2. APCB claims it exactly once.
3. APCB launches two different agent types through Herdr across separate attempts or work items.
4. Each principal receives canonical mission context from Aether.
5. One principal produces an artifact.
6. A second principal consumes the artifact through Aether state without receiving the first agent's full prompt transcript.
7. A verification result is recorded.
8. A blocked agent is detected and reconciled.
9. A Herdr restart does not duplicate the work item.
10. Unauthorized mutation remains denied.
11. Human approval remains a separate Aether event.
12. All handoffs remain reconstructable from Aether state and bridge receipts.

## Consequence

This gives Aether a practical separation of concerns:

```text
Aether = authority, memory, mission, governance, evidence
MCP    = capability interface to principals
APCB   = coordination adapter
Herdr  = local agent fleet/session execution
GitHub = versioned source control
```

The Founder no longer acts as the manual middle-man for routine handoffs. The Founder remains the constitutional authority for the actions that Aether policy requires to remain human-approved.
