# Live Web Intelligence API

All operator endpoints require `X-Aether-Operator-Token`.

## Configure a source

`POST /api/web-intelligence/configurations`

Required fields include adapter/source identity, endpoint, allowed domains, resource limits, and enabled state. Credentials are supplied only as opaque `file:`, `env:`, or `vault:` handles.

## Conform a source

`POST /api/web-intelligence/sources/{adapter_id}/conform`

A passed receipt requires all structural checks plus live canary acquisition for an enabled HTTP(S) endpoint. Receipts expire and become stale on configuration or manifest changes.

## Acquire evidence

`POST /api/web-intelligence/acquire`

Acquisition is denied unless exact conformance is passed. A successful response returns immutable snapshot identity and provenance-bound claims.

## Freshness

`POST /api/web-intelligence/freshness/run`

Evaluates age without deleting evidence and returns a bounded refresh queue.

## Adaptive discovery

```http
POST /api/web-intelligence/discover
POST /api/web-intelligence/discoveries/{candidate_id}/decision
```

Discovery proposes domains observed in existing snapshots. It does not install, configure, conform, or activate an adapter.
