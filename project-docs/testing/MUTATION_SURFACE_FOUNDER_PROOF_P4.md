# ADR-0055 P4 — Mutation-Surface Founder Proof (single principal)

## Purpose

Close ADR-0055 prerequisite 4: the Living Machine MCP mutation path reaches
`FOUNDER-PROVEN` status for a **single** principal (`chatgpt`) before any
second principal is authorized against the same mutation surface.

Status: **CLOSED** — mechanism implemented (`aether.capabilities.lifecycle`),
wired into the Living Machine MCP manifest (read-only), and the first
principal recorded end-to-end on the production runtime with observation
evidence. The mutation surface remains **single-operator in practice**: no
second principal is authorized against it.

## Truth model

```text
IMPLEMENTED -> WIRED -> CONFORMED -> ACTIVE -> FOUNDER-PROVEN
```

- **Implemented:** contract and code exist.
- **Wired:** runtime constructs the component and exposes a reachable path.
- **Conformed:** the exact adapter/environment passed a live bounded canary.
- **Active:** configuration enables the component and policy makes it eligible.
- **Founder-proven:** a real end-to-end user execution produced evidence.

## Mechanism

- `aether-core/src/aether/capabilities/lifecycle.py`
  (`aether.capability-lifecycle.v1`): deterministic state machine.
  - Consecutive transitions only (fail-closed); missing evidence blocks.
  - Append-only JSONL log; state recomputed from the log.
  - Single-principal gate: at most one founder-proven principal per surface;
    a second principal cannot become ACTIVE until the first is proven.
- `aether-core/src/aether/capabilities/lifecycle_cli.py`:
  `aether-capability-lifecycle` command for recording observation evidence.
- Wired read-only into `LivingMachineMCPService.capability_manifest()`
  (`lifecycle` key) — the manifest never advances state itself.
- Grants no authority: `ActionGovernor` and the Trusted Approval Inbox remain
  the sole authority evaluators (ADR-0055).

## Evidence recorded for the first principal (chatgpt)

| Stage | Evidence markers | Source |
|---|---|---|
| implemented | `source_present` | `workspace_edit`/`workspace_apply_patch`/`workspace_rollback` implemented in `living_machine.py`; `TOOL_SCOPE_MAP` classifies all mutation tools |
| wired | `runtime_constructed`, `path_reachable` | Gateway composes `LivingMachineMCPService`; edge `:8789` routes `/mcp`; `https://aethers.my.id/mcp` reachable |
| conformed | `canary_receipt` | governed `workspace_edit` executed end-to-end through the Trusted Approval Inbox and the local-structured coding runtime (Phase B E2E proof); runtime invocation receipt on host |
| active | `config_enabled`, `policy_eligible` | principal registry + `TOOL_SCOPE_MAP` deny-by-default live; OAuth tokens issued with `read`+`diagnostic` scopes; deny-by-default verified (unknown tool → 403, never proxied) |
| founder-proven | `founder_acceptance`, `end_to_end_receipt` | OAuth audit attribution `principal_id=chatgpt`, `auth_source=oauth` (host `audit.jsonl`); end-to-end mutation proof performed under Founder direction |

Recording command (host, observation evidence only):

```powershell
$env:AETHER_HOME = "C:\ProgramData\Aether"
aether-capability-lifecycle --to-stage wired    --evidence runtime_constructed --evidence path_reachable
aether-capability-lifecycle --to-stage conformed --evidence canary_receipt
aether-capability-lifecycle --to-stage active    --evidence config_enabled --evidence policy_eligible
aether-capability-lifecycle --to-stage founder-proven --evidence founder_acceptance --evidence end_to_end_receipt
aether-capability-lifecycle --status
```

Each stage must be observed independently before advancing. A failed
observation (e.g. runtime not reachable, canary failing) must NOT be recorded
as evidence.

## Gate verification

```text
single principal (chatgpt) recorded through full chain  -> FOUNDER-PROVEN
second principal (claude) tries to become ACTIVE
    before first is proven                              -> BLOCKED (single-principal gate)
second principal becomes ACTIVE after first is proven   -> allowed (observation)
second principal tries FOUNDER-PROVEN                   -> BLOCKED (one per surface)
```

Covered by `aether-core/tests/capabilities/test_capability_lifecycle.py`
(23 tests: contract shape, consecutive transitions, evidence fail-closed,
single-principal gate, persistence round-trip, manifest contract).

## Boundary

- This closes the ADR-0055 **prerequisite**. ADR-0055 status remains
  **Proposed** until the architecture decision owner moves it.
- No second principal is authorized against the mutation surface.
- No authority is derived from lifecycle stage; mutation still requires the
  dedicated operator submission + Trusted Approval Inbox human decision.
