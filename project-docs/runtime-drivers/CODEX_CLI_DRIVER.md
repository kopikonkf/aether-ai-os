# OpenAI Codex CLI Driver

## Status

- Driver ID: `openai-codex-cli`
- Adapter ID: `runtime.coding.openai-codex-cli`
- Routing key: `runtime://coding/openai-codex-cli`
- Aether protocol: `aether.coding-jsonl.v1`
- Implementation: live-capable

## Discovery

```bash
python aether_cli.py driver-status
```

Status semantics:

- `available`: executable, version, and authentication detected;
- `degraded`: executable detected but auth or version readiness incomplete;
- `unavailable`: executable absent or unsupported;
- `disabled`: translator not enabled or not implemented.

## Credential isolation

Only the Codex/OpenAI variables explicitly selected by the driver are forwarded. Operator, Telegram, Anthropic, Google, AWS, and unrelated environment credentials are excluded.

## Event mapping

Aether records driver discovery and translation lifecycle separately from generic runtime and coding events:

```text
runtime.driver.discovered
runtime.driver.unavailable
runtime.driver.translation.started
runtime.driver.translation.completed
runtime.driver.translation.failed
```

Vendor frames are normalized and bounded before they become Aether progress events.

## Known boundary

The driver is not the authority for success. A successful Codex turn is insufficient. Aether only reports completion after independent tests and atomic production application succeed.
