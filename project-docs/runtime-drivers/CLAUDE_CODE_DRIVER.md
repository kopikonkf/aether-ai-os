# Claude Code Driver

## Aether identity

```text
driver_id:  anthropic-claude-code
adapter_id: runtime.coding.anthropic-claude-code
routing:    runtime://coding/anthropic-claude-code
```

## Required deployment configuration

```text
AETHER_CLAUDE_BIN=/absolute/path/to/claude
AETHER_CLAUDE_API_KEY_FILE=/secure/path/anthropic.key
# or AETHER_CLAUDE_CONFIG_DIR=/secure/path/claude-config
AETHER_CLAUDE_MODEL=sonnet
```

## Boundary

Claude Code runs in non-interactive JSONL mode inside a disposable workspace. Only `Read`, `Write`, `Edit`, `Glob`, and `Grep` are allowed. Bash, web, notebooks, and agent delegation are denied. Aether independently verifies all generated file bytes.

## Conformance

```bash
python aether_cli.py driver-conformance --driver anthropic-claude-code
python aether_cli.py claude-live-demo
```

A changed executable, version, model, credential/config reference, manifest, suite, or expired receipt removes the driver from live routing.
