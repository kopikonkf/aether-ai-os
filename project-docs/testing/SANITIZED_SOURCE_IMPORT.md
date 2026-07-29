# Sanitized Source Import Receipt

Date: 2026-07-29

## Source

- Founder-accepted release: `v0.19.2-founder-alpha-frozen.2`
- Post-freeze working-tree overlays:
  - Telegram safe presentation adapter
  - shared Approval Inbox service
  - quiescent `AETHER_HOME` snapshot/import tooling
  - Windows Gateway Service foundation
  - architecture foundations and canonical handoff updates

## Excluded from source control

- real `.env` files and credentials
- `AETHER_HOME` and runtime state
- SQLite databases, WAL/SHM/journal files
- logs, backups, camera frames, and private media
- virtual environments and caches
- built wheels, ZIP archives, and generated checksum manifests

Only `.env.example` templates remain.

## Verification before import

- Python compilation: passed
- Aether Core: 148 passed
- Aether Tools: 52 passed, 1 optional skip
- Aether Gateway: 103 passed across 48 isolated test modules
- Root deployment/migration tests: 1 passed
- JSON assets parsed: 21
- YAML assets parsed: 34
- No runtime database files present
- No real `.env` file present

## Source authority

GitHub becomes the development authority after Founder review and merge. Release ZIP files remain milestone distribution artifacts only. `LASTSTANDINGPOINT.md` remains the canonical project handoff.
