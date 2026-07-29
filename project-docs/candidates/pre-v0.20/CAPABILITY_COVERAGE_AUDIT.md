# Aether v0.19.2 Capability Coverage Audit

Status: Architecture audit complete  
Scope: Ten proposed capabilities reviewed against Aether v0.19.2 source  
Decision: Do not create ten parallel subsystems. Integrate the missing decision intelligence into the existing cognitive, governance, event, memory, mission, experiment, and CEE paths.

## Executive conclusion

The proposal correctly identifies desirable behavior, but it assumes a greenfield assistant. Aether v0.19.2 already contains substantial foundations:

- provider-neutral cognition and capability routing;
- durable memory and knowledge promotion;
- event buses and audit receipts;
- autonomous goal and curiosity generation;
- prediction, reflection, and three-loop evolution prototypes;
- governed actions, trusted approvals, failure fingerprints, and reversible experiments;
- opportunity intelligence, mission orchestration, experiment budgets, runtime fleet health, and cost receipts.

The architectural gap is not ten missing features. The main gap is that these capabilities do not yet produce one normalized, evidence-bound decision envelope before consequential actions.

## Coverage matrix

| Proposed capability | v0.19.2 status | Existing evidence | Real gap | Decision |
|---|---|---|---|---|
| Emotional intelligence and context awareness | Partial / prototype | `consciousness/consciousness.py`, `reflection.py`, urgency routing, persona | No reliable Founder-state model; legacy emotion values can overclaim hidden states | Rename to `InteractionContext`; infer signals with confidence, never claim feelings as facts; defer full implementation until interaction evidence exists |
| Proactive initiative | Strong partial | `goal_generation.py`, `curiosity_engine.py`, `resonance.py`, circadian loop, runtime scheduler, opportunity scout | Sensors often depend on precomputed state; no unified trigger-to-investigation-to-notification loop | Integrate operational and business triggers during v0.20; keep authority bounded |
| Adaptive multi-step planning | Partial | mission briefs, dependencies, budgets, stop conditions, approval resume | Execution is mostly linear; no explicit branch conditions or evidence-driven replanning graph | Add branch/abort/replan contracts to mission execution after decision envelope |
| Collaborative learning | Partial | memory fabric, knowledge curator, event stores, CEE learnings | No true multi-instance merge, attribution, trust weighting, or conflict resolution | Defer until more than one real Aether instance/body produces evidence |
| Resource and constraint awareness | Strong partial | runtime fleet budgets, token/cost records, experiment budgets, opportunity expected value | Cost data is fragmented; no unified provider/runtime/tool/deployment resource ledger | Required inside v0.20; normalize cost and quota receipts before public operations |
| Explanation and transparency | Strong partial | proposal reasons, approval receipts, event lineage, plan hashes, incident rationale | No single API object explaining decision, evidence, alternatives, uncertainty, cost, and authority | Build normalized `DecisionPacket` around the metacognitive envelope |
| Creative synthesis | Partial / prototype | concept formation, generalization, curiosity, dream/war-council modules | Legacy and not consistently connected to governed experiments and measured outcomes | Do not build a separate “creative engine”; route novelty proposals into reversible experiments |
| Safety and ethics reasoning | Strong governance coverage | North Star, DNA/constitution, action governor, privacy boundaries, approvals, reversible experiments | Impact dimensions are not normalized in every external-action brief | Extend governance impact brief with privacy, harm, fairness, legal, opacity, and reversibility; do not create a competing moral authority |
| Temporal reasoning | Partial / prototype | prediction engine, timestamps, freshness scheduler, trend-related records | No general temporal graph or calibrated forecasting across operations and business | Add temporal features only where v0.20 outcomes need windows, freshness, lag, attribution, and trend detection |
| Metacognitive awareness | Strong foundation, incomplete integration | self-honesty rules, curiosity gaps, reflection, prediction evaluation, failure fingerprints | No per-decision epistemic assessment used consistently by cognition, planning, governance, and CEE | Highest-priority implementation: Evidence-Bound Metacognitive Decision Envelope |

## Priority decision

### Required in or immediately before v0.20

1. Evidence-Bound Metacognitive Decision Envelope.
2. Unified resource and cost ledger.
3. Normalized DecisionPacket / transparency view.
4. Proactive operational and opportunity triggers using real observations.
5. Adaptive branch, abort, and replan conditions for missions.

### Deferred until evidence justifies them

- broad emotional-state modeling;
- generalized creative synthesis subsystem;
- cross-instance collective intelligence;
- universal temporal reasoning engine.

## Architecture rule

Do not add a subsystem merely because a behavior has a name. Add a contract only when it creates an observable decision, receipt, boundary, or outcome that the existing architecture cannot represent.
