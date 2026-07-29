# OpenCode CLI Driver

## Identity

```text
driver_id:  opencode-cli
adapter_id: runtime.coding.opencode-cli
routing:    runtime://coding/opencode-cli
protocol:   aether.coding-jsonl.v1
```

## Configuration

```bash
export AETHER_OPENCODE_BIN=/absolute/path/to/opencode
export AETHER_OPENCODE_API_KEY_FILE=/secure/path/zen.key
export AETHER_OPENCODE_MODEL=opencode/north-mini-code-free
```

The key file should contain only the temporary API key and should be readable only by the runtime user.

## Vendor process boundary

The translator invokes OpenCode as argv, never through a shell. It builds a disposable OpenCode home and workspace and supplies restricted `OPENCODE_CONFIG_CONTENT` with:

- selected model and small model;
- sharing disabled;
- auto-update disabled;
- edit allowed;
- bash, web access, and external-directory access denied;
- provider API key supplied by `{file:...}` reference.

## Conformance

```bash
python aether_cli.py driver-conformance --driver opencode-cli
```

A successful receipt is required before the runtime can enter `CodingRuntimeRouter` candidate selection.

## Live task

```bash
python aether_cli.py opencode-live-demo
```

The demo creates a synthetic broken calculator workspace, requests a bounded correction, enters the Trusted Approval Inbox, runs independent pytest verification, and applies the result only after success.

## Current release limitation

The release builder could not install or execute the real OpenCode CLI because outbound DNS was unavailable. Use the deployment-time procedure above and revoke the temporary key after testing.
