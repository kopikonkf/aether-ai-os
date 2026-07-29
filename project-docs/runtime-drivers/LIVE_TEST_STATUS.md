# Live Runtime Test Status — MVP v0.15

Date: 2026-07-28

## Build-environment status

| Driver | Real CLI present | Deployment auth present | Real network generation performed | Deterministic translator test |
|---|---:|---:|---:|---:|
| OpenCode CLI | No | No retained credential | No | PASS |
| Google Gemini CLI | No | No | No | PASS |
| Anthropic Claude Code | No | No | No | PASS |
| OpenAI Codex CLI | No | No | No | PASS |

No real-provider success claim is made for this release.

## What deterministic tests prove

- version and CLI discovery;
- authentication readiness without secret persistence;
- exact vendor argv construction;
- structured event normalization;
- secret text redaction;
- fatal/malformed stream handling;
- generated edits in disposable workspaces;
- exact conformance receipt issuance;
- quota/rate-limit classification;
- Trusted Approval Inbox;
- independent held-out verification;
- production hash recheck;
- atomic apply or rollback;
- Runtime Operations Console evidence.

## Deployment requirement

An installed CLI must pass a fresh conformance run in its deployment environment before it enters live routing. A fake-CLI receipt is never portable to a real binary because executable path, SHA-256, and version are exact receipt inputs.
