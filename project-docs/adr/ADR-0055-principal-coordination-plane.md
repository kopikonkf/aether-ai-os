# ADR-0055 — Aether Principal Coordination Plane

- Status: Proposed (blocked on prerequisites below)
- Date: 2026-08-11
- Decision owner: Founder / Aether architecture
- Related: ADR-0008 (Governed Action Path), ADR-0010 (Trusted Approval Inbox),
  ADR-0034 (Mission Orchestrator), ADR-0048 (Founder Interactive Approval UX),
  ADR-0051 (MCP Capability Plane Baseline), ADR-0054 (renumbered
  Living Machine MCP, formerly duplicate ADR-0052)
- Independent review: Claude (Sonnet 5), 2026-08-11 — findings derived from
  direct inspection of kopikonkf/aether-ai-os @ e64de840, not accepted from
  any prior model output without independent verification.

## Context

Aether already has provider-neutral primitives for durable coordination:
`MissionOrchestrator`, `ExpectedValueBrief`, `OpportunityEvidence`,
`ActionProposal`/`ActionApproval`/`ActionDecision`, the Trusted Approval
Inbox, and `NorthStarAuthority`. It does not yet have a concept of an AI
*principal* (Claude, ChatGPT, Gemini, Qwen, Kimi, Codex, or future
MCP-capable agents) as a first-class, capability-scoped actor distinct from
"the Founder" or "an MCP connector."

`SOUL.md` currently hard-codes a single external model (the ChatGPT project
session) as "Chief Architect," which is in tension with the constitutional
invariant of provider independence. Living Machine MCP (ADR-0054) introduces
the first MUTATE-capable capability surface reachable by any MCP-connected
model, and its current mutation path synthesizes its own `ActionApproval`
inside the MCP layer rather than routing through the existing Trusted
Approval Inbox — a governance gap that must close before more principals are
authorized to reach it.

## Decision

Introduce `principal_id` and `principal_role` as attribution metadata on
existing contracts — not as new parallel data structures:

- `ActionProposal.metadata["principal_id"]`
- `MissionStep` / `ExpectedValueBrief` gain an optional `proposed_by` /
  `reviewed_by` principal attribution field
- `ActionApproval.channel` gains an enumerated value per approval source
  (`telegram`, `founder-console`, ...) — `"mcp"` alone is no longer a valid
  terminal approval channel for scopes in `approval_required`

Principal identity and capability are declared in a new, small,
Aether-owned policy document (not a runtime datastore):

```yaml
principal:
  id: claude
  role: architecture_principal
  capabilities: [architecture_review, design, diagnostic]
  mutation_authority: false   # explicit, default-deny
```

Role never implies authority. `ActionGovernor` continues to be the sole
place authority is decided, exactly as today — this ADR does not add a
second authority evaluator.

Coordination between principals happens exclusively through existing
Aether-owned canonical state (missions, evidence, decisions, receipts) —
never through direct principal-to-principal messaging. No new "AI chat bus"
is introduced.

## Prerequisites (must land before this ADR moves to Accepted)

1. Close the Living Machine MCP self-approval gap: mutation-scope actions
   reaching `ActionGovernor` with `approval_required` must be backed by an
   `ActionApproval` sourced from the Trusted Approval Inbox (or an explicit,
   named, reviewed auto-approve policy rule) — not synthesized inside the
   MCP request handler.
2. Resolve the ADR-0052 numbering collision (rename the Living Machine MCP
   ADR to ADR-0054).
3. Resolve the "Chief Architect" single-model coupling in `SOUL.md`/
   `AGENTS.md` — either generalize the role to be provider-neutral, or
   explicitly scope it as one supervisory principal among several with
   clearly bounded authority, consistent with the Provider Independence
   invariant.
4. Living Machine MCP mutation path reaches Founder-proven status (per the
   `IMPLEMENTED -> WIRED -> CONFORMED -> ACTIVE -> FOUNDER-PROVEN`
   progression) for a single principal before a second principal is
   authorized against the same mutation surface.

## Non-goals

- No unrestricted principal-to-principal message bus.
- No new "Principal Dossier" datastore parallel to missions/evidence.
- No authority derived from model identity or role name alone.
- No MCP-layer cognitive/coordination logic — MCP remains a capability
  adapter.

## Consequences

- Multiple AI principals can eventually contribute to one mission without
  duplicating Aether's evidence, decision, or receipt schemas.
- Authority remains centralized in `ActionGovernor` and the Trusted
  Approval Inbox regardless of how many principals are connected.
- Until the prerequisites land, Living Machine MCP should be treated as
  single-operator, not multi-principal, in practice — even though multiple
  MCP clients may technically hold the operator token today.
