# Aether Conformed Runtime Body

Date: 2026-07-31
Status: source-present, host-proof pending

## Decision

`aether-body` is the first conformed runtime body process. It is not the full
Nous/aether-agent body yet. It is the executable contract body that proves the
runtime rules before live provider and voice wiring.

## Runtime Contract

| Contract | Runtime body behavior |
|---|---|
| Mind authority | Body is subordinate to the Aether mind daemon |
| Mind-down behavior | Body enters fail-safe and refuses identity/goal/irreversible work |
| Mutable state | Body writes receipts and budget state under `AETHER_HOME/runtime/body/` |
| Budget | `AETHER_BODY_DAILY_CAP_USD` gates spend before any North Star request |
| Irreversible work | Body asks `/v1/north_star_evaluate` when spend or irreversible flag is present |
| Receipt | Every accept/refuse writes JSONL evidence |
| Live providers | Not wired in this slice |
| Voice | Not wired in this slice |
| Founder proof | Pending host run and receipt |

## Entrypoint

```bash
export AETHER_HOME=/opt/aether/home
export AETHER_MIND_URL=http://127.0.0.1:8765
export AETHER_BODY_HOST=127.0.0.1
export AETHER_BODY_PORT=8780
export AETHER_BODY_DAILY_CAP_USD=10
aether-body
```

Health:

```bash
curl -s http://127.0.0.1:8780/health
curl -s http://127.0.0.1:8780/v1/body/conformance
```

Task receipt smoke:

```bash
curl -s http://127.0.0.1:8780/v1/body/run \
  -H 'content-type: application/json' \
  -d '{"goal":"smoke body receipt","max_amount_usd":0}'
```

Expected receipts:

```text
$AETHER_HOME/runtime/body/receipts.jsonl
$AETHER_HOME/runtime/body/latest_receipt.json
$AETHER_HOME/runtime/body/budget_state.json
```

## Status After This Slice

| Gap | Status |
|---|---|
| One conformed runtime body | Source-present |
| Persistent `AETHER_HOME` budget state | Implemented for body actions |
| Live provider fallback | Not wired |
| LiveKit STT/TTS | Not wired |
| Active VPS proof | Pending |
| Founder-proven | Pending |
