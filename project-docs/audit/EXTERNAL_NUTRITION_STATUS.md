# External Nutrition Status — v0.19.2

## Executive verdict

The nutrition architecture exists, but the four named projects are not all live integrations.

| Source | v0.19.2 state | Live? |
|---|---|---:|
| Agent-Reach | design reference only; no adapter/CLI/doctor/skill bridge | No |
| Crawl4AI | executable restricted adapter registered in SourceCapabilityMesh | No, until dependency + configuration + conformance |
| AI TreasureBox | active static seed catalog | Not live-refreshed |
| Awesome AI Agents | active static seed catalog | Not live-refreshed |
| Generic Public HTTP | executable bounded adapter | No, disabled/unconfigured |

## Governance distinction

"External actions denied by default" does **not** mean Aether is forbidden to read the public web.

Public search, fetch, and bounded crawl are observation. They are allowed within resource, domain, provenance, robots/terms, and conformance policy.

External actions are side effects such as:

- publishing or modifying a public deployment;
- sending outreach, email, posts, or messages to third parties;
- creating accounts or changing credentials/permissions;
- spending money, placing orders, or initiating payment;
- modifying customer or lead records in an external system;
- making legal, contractual, or irreversible commitments.

Those actions require explicit authority appropriate to their consequence. Observation does not silently grant execution authority.

## Correct integration direction

- Keep Crawl4AI behind `Crawl4AIRestrictedAdapter`.
- Add an `AgentReachSourcePackAdapter` or governed runtime bridge rather than running its installer with unrestricted authority.
- Convert AI TreasureBox and Awesome AI Agents from static seeds into versioned live catalog adapters with commit/hash provenance and scheduled refresh.
- Require a bounded canary and exact conformance receipt before any adapter becomes eligible.
