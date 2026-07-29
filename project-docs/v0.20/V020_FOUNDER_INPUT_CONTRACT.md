# MVP v0.20 — Founder Input Contract

## Status

Reserved until the v0.19.2 real bring-up evidence is accepted. No further legacy source code is required to begin architectural preparation.

## Required Founder inputs after bring-up

Only the following business/operations choices are required. Everything else should receive an explicit default in implementation.

| Field | Purpose | Example |
|---|---|---|
| `offer.name` | What Aether is allowed to ship | AI operations audit |
| `offer.target_user` | Intended user/customer | Indonesian small agencies |
| `offer.promise` | Bounded value proposition | Find and prioritize workflow automation opportunities |
| `experiment.success_event` | Primary demand proof | qualified waitlist submission |
| `experiment.budget_cap_usd` | Maximum external spend before renewed approval | 50 |
| `deployment.target` | First replaceable public adapter | generic Docker VPS |
| `analytics.sink` | Evidence destination | generic signed webhook |
| `lead.required_fields` | Minimal lead ledger schema | email, consent, source |
| `approval.channel` | Where consequence approvals arrive | Telegram + AionUi |
| `revenue.evidence_source` | How revenue linkage is verified | payment webhook or manual signed record |
| `rollback.owner` | Human accountable for emergency rollback | Founder |

Fill `v020-founder-inputs.example.yaml` and rename it to `v020-founder-inputs.yaml` outside version control.

## Default architecture decisions unless Founder overrides

1. External actions are denied by default.
2. Preview deployment precedes public promotion.
3. Every promotion references an impact brief and approval receipt.
4. Deployment providers sit behind a replaceable adapter contract.
5. Analytics and lead events enter an append-only evidence ledger.
6. Revenue claims require a verified payment or signed manual record; model inference is insufficient.
7. Every public experiment has rollback and kill-switch operations.
8. Portfolio reallocation requires comparable evidence windows and bounded budget authority.
9. CEE learning updates strategy evidence, never silently expands authority.

## Not required from the Founder

- another conceptual architecture document;
- a final list of every future deployment or analytics provider;
- production credentials inside chat;
- a complete portfolio strategy before the first measured experiment.

## Build gate

Implementation of v0.20 begins when both are true:

```text
v0.19.2 real bring-up accepted
AND
v020-founder-inputs.yaml contains the required fields
```
