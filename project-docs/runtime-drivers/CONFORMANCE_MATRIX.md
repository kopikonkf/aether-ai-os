# Runtime Driver Conformance Matrix — MVP v0.15

| Driver | Translator | Discovery | Auth isolation | Streaming normalization | Disposable workspace | Independent verification | Exact receipt | Runtime status in build environment |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| OpenCode CLI | PASS | PASS | PASS | PASS | PASS | PASS | PASS | CLI unavailable |
| Google Gemini CLI | PASS | PASS | PASS | PASS | PASS | PASS | PASS | CLI unavailable |
| Anthropic Claude Code | PASS | PASS | PASS | PASS | PASS | PASS | PASS | CLI unavailable |
| OpenAI Codex CLI | PASS | PASS | PASS | PASS | PASS | PASS | PASS | CLI unavailable |
| Cursor Agent | NOT IMPLEMENTED | Manifest only | N/A | N/A | N/A | N/A | NOT ELIGIBLE | Disabled |

## Receipt gate

A driver is eligible only when all of the following match a non-expired append-only receipt:

```text
manifest fingerprint
executable path and SHA-256
CLI version
Aether protocol
provider and model
non-secret configuration-reference hash
conformance suite
operator and expiry
```

## Governance boundary

Conformance means the installed binary matches a verified operational contract. It does not authorize a coding task, grant a workspace binding, or approve a production mutation.
