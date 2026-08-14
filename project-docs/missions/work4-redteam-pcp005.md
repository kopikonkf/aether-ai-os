# WORK-4 — Red-team adversarial checklist (MISSION-PCP-005 / Gate 6)

- Date: 2026-08-14 · Owner: COORD (kimi w7:p8 limit s/d Aug 18 → COORD checklist per founder)
- Test file: `aether-core/tests/executive/test_cognitive_redteam_pcp005.py` (6 tests, all PASS)
- Baseline: aether-core 531/531 PASS (was 510 baseline → +15 WORK-1/2/3 + 6 WORK-4)

## Checklist probed (per PCP-005 breakdown C WORK-4)

| # | Item | Result |
|---|------|--------|
| R1 | Per-step principal routing: distinct principal per step, registered | PASS — `_directive()` 5 distinct principals, validate(profiles) OK |
| R2 | Profile validation fail-closed: step profile must belong to its principal | **FINDING FIXED** (see R-PCP005-1) |
| R3 | Artifact envelope per principal (ADR-0057) | PASS — evidence per-step principal_id + artifact_present all True |
| R4 | K3 re-dispatch antar principal / no cross-principal cascade on failure | PASS — step-3 fail stops loop; deepseek+chatgpt never dispatched |
| R5 | Dependency chain lintas principal (artifact chain) | PASS — step N+1 prompt carries step N artifact across principal change |
| R6 | Budget / governance once with 5 principals | PASS — governance_count==1, 5-step COMPLETED |
| R7 | No duplicate principal per mission bila acceptance minta | PASS — require_distinct_principals=True rejects dup |

## Finding R-PCP005-1 (found + fixed)

- **Symptom:** `CognitiveDirective.validate(profiles=...)` did not verify a per-step
  `execution_profile` is one the step's principal is actually registered with.
  `claude` + `herdr:opencode` (a profile owned by `chatgpt`) passed plan-time
  validate, then either silently remapped at dispatch or failed late at
  eligibility — not fail-closed at the plan boundary.
- **Fix:** `validate(profiles=...)` now appends blocker
  `step <id> profile <profile> not registered to principal <principal>` whenever a
  step carries an explicit profile the principal lacks.
- **Tests:** `test_redteam_rejects_step_profile_not_registered_to_principal`,
  `test_redteam_rejects_step_profile_belongs_to_wrong_principal`.

## Finding R-PCP005-2 (accepted as-by-design)

- Duplicate principals across steps are only rejected when
  `require_distinct_principals=True` (set by `RuleBasedReasoner` when
  `step_principals` is used). Legacy multi-step (single shared principal,
  PCP-004) stays valid — backward compat is a hard requirement, so no change.

## Tests added
1. `test_redteam_rejects_step_profile_not_registered_to_principal`
2. `test_redteam_rejects_step_profile_belongs_to_wrong_principal`
3. `test_redteam_legacy_shared_principal_still_valid`
4. `test_redteam_all_steps_distinct_registered_with_owning_profiles`
5. `test_redteam_multi_principal_loop_invariants` (5-step COMPLETED, distinct principals, artifact chain)
6. `test_redteam_mid_chain_failure_stops_later_principals` (step-3 fail → stop, S4/S5 never dispatched)

## NON-ACTIVATION
- Local-only. No push/merge until verdict. No live herdr dispatch.
