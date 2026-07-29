# ADR-0027: First Live-Capable Driver — OpenAI Codex CLI

- Status: Accepted
- Date: 2026-07-28

## Decision

The first live-capable generative coding driver is `openai-codex-cli`.

The translator invokes Codex CLI non-interactively, consumes vendor JSONL events, normalizes progress into `aether.coding-jsonl.v1`, and emits complete-text patch frames to Aether's generic external runtime adapter.

## Invocation boundary

The translator uses argv execution without a shell. Its intended command shape is equivalent to:

```text
codex --ask-for-approval never --sandbox workspace-write exec \
  --json --ephemeral --ignore-user-config --ignore-rules \
  --skip-git-repo-check --color never -
```

The coding objective is delivered through stdin. An optional model is appended through `--model` only when explicitly configured.

## Workspace boundary

Codex never receives the production workspace and does not mutate Aether staging directly. The translator creates a second temporary vendor workspace copied from staging. After Codex exits successfully, the translator computes before/after snapshots and emits bounded patch artifacts.

Aether independently:

1. validates paths and hashes;
2. applies patches to staging;
3. runs held-out verification;
4. rechecks production hashes;
5. atomically applies or rolls back.

## Streaming normalization

Supported vendor events include thread, turn, item, command, file-change, message, reasoning, warning, completion, and failure events. Item-level error records are treated as non-terminal warnings unless the turn fails or the process exits unsuccessfully.

Vendor event volume is bounded. Low-priority events beyond the normalization cap are summarized rather than forwarded indefinitely.

## Authentication

The driver detects either an explicitly forwarded `OPENAI_API_KEY` or an existing Codex credential file under the configured Codex home. Authentication values are never persisted in status, events, transcripts, or telemetry.

## Verification limitation

No Codex executable or credential was present in the release environment. Real network-backed generation was therefore not executed. A deterministic fake CLI verified the full translator and governed patch pipeline. The driver is live-capable, but live availability remains an installation-time property.
