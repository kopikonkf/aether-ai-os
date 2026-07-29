# Mission Orchestrator API

All endpoints require:

```http
X-Aether-Operator-Token: <trusted-token>
```

## Opportunity intake

```http
POST /api/opportunities
GET  /api/opportunities
```

External-value intake requires two independent supporting sources with external
references. Contradictions remain blockers and are not silently reconciled.

## Mission plan lifecycle

```http
POST /api/missions/plans
GET  /api/missions
GET  /api/missions/{mission_id}

POST /api/missions/{mission_id}/approve
POST /api/missions/{mission_id}/reject
POST /api/missions/{mission_id}/run
POST /api/missions/{mission_id}/resume
POST /api/missions/{mission_id}/pause
POST /api/missions/{mission_id}/cancel
```

Mission-plan approval authorizes the bounded plan to start. It does not approve
write, network, runtime, memory, or irreversible step actions. Those actions
continue through the Trusted Approval Inbox.

## Value and outcome evidence

```http
POST /api/missions/{mission_id}/value-evidence
POST /api/missions/{mission_id}/outcome
```

Value kinds are `claimed`, `realized`, and `verified`. Only realized and verified
amounts are revenue evidence. Outcome finalization requires a terminal execution
state and trusted operator identity.

## Console

```http
GET /api/mission-operations/console
GET /aionui/mission-console
```

The embedded WebUI is a fallback operator shell. The native AionUi integration
pack keeps the operator token in Electron's main process and exposes bounded IPC
methods to the renderer.
