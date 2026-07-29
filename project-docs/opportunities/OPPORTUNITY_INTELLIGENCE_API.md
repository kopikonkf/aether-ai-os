# Opportunity Intelligence API

All endpoints require the configured `X-Aether-Operator-Token` except console static assets.

## Run a scout

```http
POST /api/opportunity-intelligence/scout-runs
```

```json
{
  "objective": "AI workflow automation opportunities",
  "queries": ["automation agent", "repetitive workflow pain"],
  "source_kinds": ["catalog", "web"],
  "maximum_sources": 12,
  "maximum_snapshots": 40,
  "maximum_bytes": 4000000,
  "maximum_duration_seconds": 300,
  "autonomy_level": "observe"
}
```

## Synthesize candidate

```http
POST /api/opportunity-intelligence/candidates
```

Requires claim IDs already stored by scout/extraction.

## Score portfolio

```http
POST /api/opportunity-intelligence/portfolio/score
```

This is deterministic and does not select candidates.

## Select, defer, or reject

```http
POST /api/opportunity-intelligence/candidates/{candidate_id}/decision
```

Only trusted Founder/operator identities can create terminal portfolio decisions.

## Issue experiment mandate

```http
POST /api/opportunity-intelligence/candidates/{candidate_id}/mandates
```

Requires a prior `select` decision. Mandate cost cannot exceed portfolio allocation.

## Convert to mission evidence brief

```http
POST /api/opportunity-intelligence/candidates/{candidate_id}/convert-to-mission
```

Conversion creates a reviewable mission brief only. It does not create a plan or approve execution.
