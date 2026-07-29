# Ralph Loop → Aether Internal Evolution Adaptation

## Source-derived mechanics retained

The uploaded Ralph implementations organize work around one task per invocation, fresh agent contexts, a durable task/PRD state, iteration limits, testing before completion, progress logs, steering instructions, explicit complete/blocked/decision signals, and sandbox-oriented execution.

## Aether translation

| Ralph mechanic | Aether v0.8 mechanism |
|---|---|
| One task per invocation | One target artifact per candidate |
| Fresh agent context | Fresh baseline and candidate sandbox copies |
| Task state and logs | Append-only SQLite trigger/candidate/evaluation ledger |
| Tests/lint/type checks | Deterministic command phase |
| Completion evidence | Held-out evaluation plus measurable improvement |
| Steering/decision tag | Trusted operator promotion or rejection |
| Git commit history | Content hashes, backup path, and durable lineage |
| Retry loop | New candidate or explicit retry reason |
| Sandbox | Replaceable `EvolutionSandbox` port |

## Deliberate divergence

Aether does not permit an optimizing model to bypass permissions, mutate production directly, modify DNA/Northstar, treat a commit as sufficient proof, or declare success without held-out evidence. External business evolution is not coupled to the coding loop.
