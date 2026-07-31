# AionUi / Senses Public Health

Date: 2026-07-31
Status: source-present, host-proof pending

## Decision

Expose a public health surface for AionUi and unified browser senses from
Aether Gateway. AionUi may render the operator shell, but the public status
contract is owned by Gateway and keeps cognition, memory, identity, and
governance in Aether.

## Public Routes

| Route | Purpose |
|---|---|
| `/health` | Gateway public health summary, including browser-senses status |
| `/api/browser-senses/status` | JSON contract consumed by AionUi `/senses` |
| `/senses` | Public status page for the browser-senses surface |
| `/senses/app.js` | Status page JavaScript |
| `/senses/styles.css` | Status page styles |
| `/senses/manifest.json` | Browser-senses console manifest |

## Contract Notes

- Missing LiveKit SDK or credentials is non-fatal and reports
  `mode: browser-fallback`.
- AionUi sidecar wiring reports whether `AIONUI_COMMAND` is configured without
  exposing the command itself.
- Public one-domain deployment reports `AETHER_PUBLIC_BASE_URL` when present.
- Browser media still requires HTTPS or localhost plus explicit browser
  permission.

## Verification

Implemented locally:

- pure status payload smoke for `/health` and `/api/browser-senses/status`;
- static `/senses` page, JS, CSS, and manifest source;
- compile sanity for gateway public health module, gateway server, and tests.

Pending host proof:

- FastAPI route test under full repo dependencies;
- public HTTPS smoke against the real domain;
- AionUi renderer fetch of `/api/browser-senses/status`;
- real browser permission flow.

