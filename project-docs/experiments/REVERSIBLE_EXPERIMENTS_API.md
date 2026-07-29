# Reversible Experiments API

All mutation endpoints require `X-Aether-Operator-Token`.

## Create plan

`POST /api/experiments/plans`

The request binds a selected opportunity and active mandate to success metrics, stop conditions, fixed steps, and cost/duration/byte/file budgets.

## Run plan

`POST /api/experiments/plans/{plan_id}/run`

Execution is idempotent for completed/preview-ready plans. A successful private preview returns its capability token once.

## Read private preview

`GET /api/experiments/previews/{preview_id}/{token}/{relative_path}`

The server verifies token hash, expiry, and path containment.

## Demand signals

`POST /api/experiments/runs/{run_id}/demand-signals`

Synthetic signals must remain synthetic. Measured signals require an external reference. Verified signals additionally require a trusted verifier.

## External review

```http
POST /api/experiments/runs/{run_id}/external-reviews
POST /api/experiments/external-reviews/{review_id}/decision
```

Review approval is evidence for the requested external action; it does not silently add arbitrary execution capability to the reversible runner.
