# ADR-0057 — APCB Governance: Artifact Authority over Receipt Observation (K1)

- Status: Proposed (2026-08-13 — Gate 3 MISSION-HETERO-001 PASS-WITH-BLOCKERS;
  blockers K1-K5 from WORK-4/WORK-5; decision owner: Founder / Aether
  architecture, review via ChatGPT)
- Date: 2026-08-13
- Decision owner: Founder / Aether architecture
- Related: ADR-0055 (Principal Coordination Plane), ADR-0056 (OAuth Edge /
  Herdr bridge), ADR-0034 (Mission Orchestrator), APCB v0.1 Implementation
  Contract
- Evidence: `WORK-HETERO-005.md` (WORK-5 verdict), `WORK-HETERO-004.md`
  (K1-K16), `WORK-HETERO-003.md` (qwen implementation) — all in
  `C:\Users\aethers\AppData\Local\Temp\opencode\apcb-hetero-001\`

## Context

During Gate 3 (MISSION-HETERO-001) the APCB receipt chain and the produced
artifacts diverged:

- WORK-3 (qwen) produced a real artifact `WORK-HETERO-003.md` and a passing
  deterministic test (`test_apcb_invariant_mapping.py`, 7/7 then 8/8 after the
  pane-map fix), yet the receipt row recorded `terminal_outcome=failed`
  (window/settle timeout, not a work failure).
- WORK-1 attempt-2 recorded `completed` with no accepted artifact; attempt-3
  re-dispatched with no explicit reconcile record (K3).

Two conflicting authorities emerged: the **receipt** (observation-level) and
the **artifact + test evidence** (work product). Consumers could not tell which
was canonical.

## Decision

**Artifact + test evidence is the acceptance authority for work deliverables.
The receipt is an observation-level execution record, not the acceptance
authority.**

Concretely:

1. A terminal receipt row is a **dispatcher observation** (dispatched /
   prompted / observed / timed out). It records what the bridge *observed*,
   never what Aether *accepted*.
2. A deliverable is **accepted** when the expected artifact exists with
   non-zero length, the envelope parses, and `work_id`/`principal_id`/`attempt`
   match the work item — and, where applicable, its tests pass. Acceptance
   decision belongs to Aether (Slice C), not to the APCB write path.
3. Where a terminal receipt says `failed`/`unknown` but the artifact is valid,
   the dispatcher emits a reconcile note (`reconcile_artifact_found`) and the
   work is treated as delivered-with-evidence. The receipt row is not rewritten
   (append-only); a new authoritative event carries the artifact status.
4. Where a terminal receipt says `completed` but no artifact exists, the
   outcome is `completed_without_artifact` and the work is **not** accepted —
   it requires reconcile or a governed retry (K3 gate).
5. This ADR does not grant authority: `mutation_authority` remains governed by
   Aether policy (ADR-0055). Acceptance of code changes still requires the
   normal verification/approval gates.

### Consequences

- Consumers must treat `terminal_outcome` as *observation*, and require the
  artifact/evidence manifest (sha256 + path + envelope) for acceptance.
- `terminal_outcome=unknown` is non-terminal for acceptance purposes: it must
  resolve to `completed` (artifact found), `failed`, or `abandoned` only after
  artifact + pane inspection.
- The K2 (terminal uniqueness), K3 (re-dispatch reconcile), K4 (pane
  uniqueness), and K5 (structured fuel) rules are implemented alongside this
  ADR so the whole governance surface moves together.

## Status of accompanying governance rules

- K2 Terminal uniqueness — implemented: `ReceiptStore` raises
  `DuplicateTerminalError` on a second terminal write per tuple; dispatcher
  reconcile short-circuits on already-terminal receipts.
- K3 Re-dispatch reconcile gate — implemented: new attempt after a terminal
  prior attempt requires `needs_reconcile` or `approval_id` in work metadata.
- K4 Pane uniqueness — implemented: `validate_pane_map_unique()` fail-closed at
  CLI startup; sovereign principals must never share a pane.
- K5 Structured fuel — implemented: `model_provider` structured field on each
  sovereign principal in `principal_runtime_profiles.v0.yaml`, sourced by the
  invariant test (replaces the hard-coded `FUEL_BY_PRINCIPAL` fixture).
