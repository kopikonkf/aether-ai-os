# Aether CLI Decision

Status: ACCEPTED FOUNDATION, NOT YET SHIPPED
Date: 2026-07-29

## Current truth

Aether already owns a cross-platform developer entrypoint at `aether_cli.py` and package-level commands such as `aether-gateway`, `aether-boot`, `aether-check`, and `aether-daemon`.

The root CLI is useful and broad, but it is not yet a stable installed control-plane command named `aether`. Its command definitions are local to one large script and are not shared with Telegram or the future AionUi control surface.

## Decision

Create a first-class `aether` CLI before Founder Acceptance, without making the CLI another cognitive runtime.

The CLI is a thin control surface over existing Aether services, stores, and governance. It must not duplicate Mind logic or bypass action policy.

## Initial stable surface

Read-only commands:

- `aether version`
- `aether paths`
- `aether status`
- `aether doctor`
- `aether context status`
- `aether context doctor`
- `aether skills status`
- `aether runtime status`
- `aether approvals list`

Governed commands:

- `aether approvals approve <id> --reason <text>`
- `aether approvals reject <id> --reason <text>`
- `aether context compact [--session <id>]`
- `aether memory rebuild`
- `aether services start|stop|restart`

## Invariants

1. Human output and `--json` output are both supported.
2. Stable exit codes are documented.
3. Mutating commands use the same approval/governance contracts as Telegram and API.
4. No command imports provider secrets into output.
5. Command registry metadata is reusable by Telegram and AionUi where semantics match.
6. Runtime-specific commands remain under runtime adapters.
7. Existing `aether_cli.py` remains a developer verification harness until commands are migrated deliberately.

## Delivery gate

The installed `aether` command is targeted for the VPS-ready release, after Windows Service supervision is available. It is not required to reopen the accepted laptop baseline.
