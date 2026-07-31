# ADR-0049 — Telegram Command Registry and Founder Inline Approval

**Status:** Accepted; implemented in working tree; not yet packaged.

## Decision

Telegram remains a communication/sense adapter. Machine approval authority stays in the trusted approval inbox and API. Telegram projects that authority into a Founder-friendly UI.

### One-tap approval

Pending actions render as a compact card with:

- `Approve once`;
- `Reject`;
- `Details`.

Callback payloads are compact and HMAC-signed, bind to one exact approval ID, and are checked against the trusted Telegram user and originating chat. Approval remains exact-once, expiring, action-hash-bound, and durably receipted.

Typed `/yes`, `/no`, `/approve`, and `/reject` remain fallback controls.

### Command registry

A single registry owns:

- canonical command name;
- aliases;
- handler binding;
- menu visibility;
- operator-only metadata;
- category and help description.

The same registry generates handler registration, `/help`, and Telegram's command menu. Gateway startup fails if a registered command does not have a real handler.

Only live commands are exposed. Aspirational features are never advertised as commands.

### Initial command surface

- `/start`;
- `/help`;
- `/new` (`/clear` compatibility alias);
- `/status`;
- `/model`;
- `/approvals`;
- `/yes`;
- `/no`;
- hidden explicit `/approve` and `/reject` fallbacks.

Natural language remains the primary interface.
