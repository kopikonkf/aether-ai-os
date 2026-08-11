# APCB v0.1 — Aether Principal Coordination Bridge Implementation Contract

- Status: Proposed implementation contract
- Date: 2026-08-11
- Related: ADR-0034, ADR-0055, ADR-0056
- Scope: local-first coordination between Aether canonical mission state and Herdr-managed agent execution

## 1. Objective

APCB exists to remove the Founder from routine agent-to-agent handoff without introducing a second cognitive authority or a model-to-model chat bus.

The contract is:

```text
Aether = canonical state + authority
MCP   = capability interface
APCB  = deterministic coordination adapter
Herdr = local agent/session execution fabric
Agent = replaceable principal runtime
GitHub = versioned source control
```

APCB may observe and dispatch execution. It may not decide mission policy, approve governed mutation, create canonical decisions, or become the system of record for work ownership.

## 2. Runtime topology

```text
                    AETHER GATEWAY / CORE
               ┌───────────────────────────┐
               │ Mission / Memory         │
               │ Evidence / Decisions     │
               │ Governance / Approvals   │
               │ Runtime receipts         │
               └─────────────┬─────────────┘
                             │
                       Aether service API
                             │
                             ▼
                    ┌─────────────────┐
                    │      APCB       │
                    │ claim/dispatch  │
                    │ observe/reconcile│
                    └────────┬────────┘
                             │ local
                             ▼
                         Herdr
                             │
             ┌───────────────┼────────────────┐
             ▼               ▼                ▼
          Claude           Codex           Kimi/Qwen/etc.
             │               │                │
             └───────────────┼────────────────┘
                             │
                             ▼
                     artifacts / status
                             │
                             ▼
                          APCB
                             │
                             ▼
                    Aether canonical state
```

Remote principals that are not local Herdr processes use the other path:

```text
Principal host -> authenticated Aether MCP -> Aether
```

Herdr is therefore optional for a principal, but APCB is the local bridge when a principal executes on the Aether host or attached development machine.

## 3. Aether remains the authority

The APCB must use existing Aether mission contracts and services wherever possible. The initial integration target is the existing `MissionOrchestrator` and mission store; do not create a parallel work database merely for APCB.

Existing mission execution already models step attempts, retry limits, waiting approval, failure fingerprints, bounded continuation, and terminal states. APCB should project an eligible mission step into an execution lease and return runtime evidence to the same canonical mission state.

Aether state transitions remain authoritative. Herdr state never directly changes a mission status.

## 4. Dispatch eligibility

A work item is dispatchable only when all are true:

1. The mission/step is already authorized by Aether policy.
2. The step is in an execution-ready state.
3. `principal_id` is explicitly assigned.
4. The principal execution profile is enabled.
5. Required capabilities match the principal profile.
6. A valid workspace binding exists.
7. No active APCB attempt already owns the work item.
8. The work item is not awaiting human approval.

APCB must never promote a blocked or approval-waiting step into Herdr execution.

## 5. Durable coordination identity

Every dispatch uses an idempotency tuple:

```text
(work_id, attempt_number, principal_id)
```

The bridge must persist its own execution receipt keyed by this tuple before asking Herdr to start work.

A second poll, APCB restart, or Herdr reconnect must reconcile the existing receipt before dispatching again.

No new mission step is created merely because a process restarted.

## 6. APCB state machine

Canonical Aether state:

```text
READY
  -> CLAIMED
  -> DISPATCHED
  -> RUNNING
  -> REVIEW
  -> COMPLETED

RUNNING -> BLOCKED
RUNNING -> FAILED
```

APCB-local execution state:

```text
DISCOVERED
  -> CLAIM_REQUESTED
  -> CLAIMED
  -> HERDR_ATTACHED
  -> PROMPTED
  -> OBSERVING
  -> RECONCILING
  -> TERMINAL
```

The bridge must never invent a terminal Aether state. It translates observations into an Aether service call which performs the authoritative transition.

## 7. Principal profile registry

Use an Aether-owned configuration registry, not Herdr configuration, to map principals to execution profiles.

Example shape:

```yaml
principals:
  claude:
    role: architecture_principal
    capabilities: [architecture_review, design, diagnostic]
    mutation_authority: false
    execution_profiles: [herdr:claude]

  qwen:
    role: implementation_principal
    capabilities: [implementation, testing, refactoring]
    mutation_authority: false
    execution_profiles: [herdr:qwen]

execution_profiles:
  herdr:claude:
    herdr_kind: claude
    workspace_mode: bound
  herdr:qwen:
    herdr_kind: qwen
    workspace_mode: bound
```

Important invariants:

- `principal_id` is identity/attribution, not authorization.
- `role` never implies mutation authority.
- Execution profile maps to a known Herdr integration or a controlled compatible-agent profile; it must not contain arbitrary shell text.
- Mutation authority remains governed by Aether policy.

## 8. Herdr adapter boundary

APCB must depend on the highest-level stable Herdr interface sufficient for the operation.

Preferred order:

1. Herdr CLI wrappers for simple request/response operations.
2. Herdr local socket API for long-lived orchestration, state observation, and event subscriptions.
3. Raw terminal/pane control only as a compatibility fallback for an agent without a suitable integration.

The Herdr adapter should expose a narrow internal protocol:

```python
class HerdrExecutionAdapter(Protocol):
    async def ensure_workspace(self, workspace_ref: str) -> str: ...
    async def ensure_agent(self, workspace_ref: str, principal_id: str) -> str: ...
    async def prompt_agent(self, agent_ref: str, task_context: str) -> str: ...
    async def observe_agent(self, agent_ref: str) -> "AgentObservation": ...
    async def wait_agent(self, agent_ref: str, timeout_seconds: float) -> "AgentObservation": ...
    async def read_agent(self, agent_ref: str, limit_bytes: int) -> str: ...
    async def recover_agent(self, agent_ref: str) -> "AgentObservation": ...
```

This adapter must normalize Herdr-specific workspace/tab/pane/session identifiers into opaque execution references stored as bridge metadata.

Herdr's current public surface includes a local socket API, persistent server/client sessions, agent-aware lifecycle/state, and native integrations for several coding agents. Exact command/socket details must be discovered from the installed Herdr version at runtime rather than hard-coded from a stale documentation snapshot. citeturn895327search0turn895327search1

## 9. Prompt envelope

APCB must not forward an entire principal conversation to another principal.

Every task prompt should be constructed from canonical Aether artifacts only:

```json
{
  "protocol": "aether.apcb.task.v1",
  "work_id": "WORK-...",
  "mission_id": "MISSION-...",
  "principal_id": "qwen",
  "attempt": 1,
  "objective": "...",
  "constraints": ["..."],
  "acceptance_criteria": ["..."],
  "relevant_decisions": ["DEC-..."],
  "relevant_artifacts": ["ART-..."],
  "relevant_evidence": ["EV-..."],
  "workspace_id": "...",
  "correlation_id": "..."
}
```

The agent may add a proposed handoff summary, but APCB must treat the returned summary as untrusted evidence until Aether services accept it.

## 10. Agent-to-agent handoff

There is no direct Claude -> Qwen message path.

The handoff is:

```text
Claude
  -> artifact/decision/evidence
  -> Aether canonical state
  -> new work item assigned to Qwen
  -> APCB
  -> Herdr
  -> Qwen
```

Minimum handoff record:

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

This is an Aether artifact. It is not a Herdr message.

## 11. Reconciliation rules

APCB must reconcile before retrying whenever any of these occur:

- APCB restart;
- Herdr restart;
- bridge process timeout;
- lost socket connection;
- agent pane exit;
- workspace disappearance;
- stale claim;
- ambiguous completion;
- duplicate dispatch request.

Reconciliation order:

```text
1. Load APCB receipt by (work_id, attempt, principal_id)
2. Query Herdr execution state
3. Inspect Aether mission state
4. If Aether is terminal -> stop
5. If Herdr is still running -> resume observation
6. If Herdr is complete but Aether is not terminal -> promote result through Aether service
7. If Herdr is gone and Aether is non-terminal -> record failure/blocked evidence
8. Only then consider a retry using the same work_id with incremented attempt
```

APCB must never silently reassign an owned work item to another principal.

## 12. Mutation boundary

APCB is not an approval mechanism.

It must never:

- create a trusted `ActionApproval` merely because a principal is authenticated;
- reuse the Living Machine MCP operator credential as principal identity;
- bypass `ActionGovernor`;
- bypass `GovernedActionPath`;
- treat Herdr prompt submission as human approval;
- promote a runtime observation directly into a constitutional decision.

A principal may propose a mutation. The Aether governance/approval layer decides whether it can execute.

This contract remains blocked on the Living Machine MCP self-approval remediation identified by ADR-0055.

## 13. Service identity

APCB authenticates to Aether as a dedicated service identity, for example:

```text
principal-coordination-bridge
```

This service identity is distinct from:

```text
AETHER_MCP_TOKEN
AETHER_MCP_OPERATOR_TOKEN
principal_id
Herdr credentials
provider API keys
```

The service identity grants only the Aether service calls required to coordinate work. It is not a mutation superuser.

## 14. Evidence normalization

Agent output must be classified into one of three forms:

```text
OBSERVATION  -> raw runtime fact
ARTIFACT     -> bounded output associated with work
PROPOSAL     -> model-generated recommendation requiring Aether evaluation
```

APCB must not silently convert raw agent text into a canonical decision.

Large output must remain bounded and reference-backed. The bridge should prefer hashes, artifact identifiers, verification receipts, and short summaries over full transcripts.

## 15. Initial implementation package

After ADR-0055 prerequisites are satisfied, the implementation should be split into reviewable units:

### Slice A — contracts/config

- principal profile registry;
- bridge execution receipt contract;
- principal handoff artifact contract or extension of an existing canonical event/metadata shape;
- APCB service identity configuration.

### Slice B — Herdr adapter

- local CLI/socket capability detection;
- workspace/agent lookup;
- start/prompt/read/wait/recover;
- normalized observations;
- protocol/version diagnostics.

### Slice C — Aether coordination adapter

- ready-work discovery;
- optimistic claim;
- dispatch receipt;
- terminal reconciliation;
- bounded retry/recovery.

### Slice D — proof harness

- two heterogeneous principals;
- one artifact handoff;
- one blocked/recovery scenario;
- one Herdr restart scenario;
- no duplicate work item;
- no approval bypass.

Do not implement all four slices in one PR.

## 16. Founder-proof acceptance test

The first real-world demonstration should be deterministic and small:

```text
MISSION-APCB-001
  |
  +-- WORK-A -> Claude: architecture artifact
  |
  +-- WORK-B -> Qwen/Codex: implementation consuming WORK-A artifact
```

Success requires:

1. Aether creates both work items.
2. APCB claims each exactly once.
3. Herdr starts the assigned principals.
4. Claude publishes an artifact to Aether.
5. Qwen/Codex receives only canonical Aether context, not Claude's full transcript.
6. The implementation is verified.
7. APCB survives a controlled Herdr restart without duplicate dispatch.
8. Aether can reconstruct the full handoff from work/evidence/receipt state.
9. No mutation occurs through a self-synthesized approval.

## 17. Operational observability

Every APCB operation must expose:

```text
bridge_request_id
work_id
mission_id
principal_id
attempt
herdr_execution_ref
correlation_id
action/status observed
time
terminal outcome
```

Logs must be bounded and must not include provider tokens, MCP bearer credentials, raw secrets, or unredacted prompt payloads.

## 18. Implementation rule

APCB should remain boring.

If a new requirement can be satisfied by an existing Aether mission, evidence, governance, runtime, memory, or receipt primitive, reuse it.

If a requirement is specific to local agent process/session control, it belongs in the Herdr adapter.

If a requirement is about deciding what Aether should do, it does not belong in APCB.
