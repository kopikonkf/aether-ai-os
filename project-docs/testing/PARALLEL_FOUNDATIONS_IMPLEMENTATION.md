# Parallel Foundations Implementation

Status: staged in the pre-Founder-acceptance working tree; not installed on the accepted laptop baseline.

## Telegram presentation

- Added a conservative `TelegramPresentationAdapter`.
- Supports safe headings, bold, italic, underline, strike, links, lists, inline code, fenced code, block quotes, and bounded message splitting.
- Raw HTML is escaped.
- Unsafe link schemes do not become clickable links.
- Telegram API formatting failure falls back to plain text.
- Cognition receives an authoritative channel capability snapshot and is instructed not to promise unsupported structured Rich Messages or streaming.
- Bot API 10.2 structured Rich Messages remain a later stage; current implementation is safe HTML presentation.

## Shared Approval Inbox service

- Added `ApprovalInboxService` as the common application boundary for Telegram, HTTP/AionUi, and future collaboration surfaces.
- Centralizes expiry sweeping, list/get, context filtering, exact-once decision routing, and optional action-hash binding.
- HTTP decisions may include `expected_action_hash` to prove the UI acted on the exact operator-visible action.
- Transport authentication remains local to Telegram or HTTP; governance and execution remain shared.

## Quiescent AETHER_HOME migration

- Added cross-platform `scripts/aether_home_snapshot.py`.
- SQLite databases are copied through the SQLite backup API and verified with `PRAGMA quick_check`.
- WAL/SHM/journal sidecars are excluded from the snapshot.
- Every file receives a SHA-256 manifest entry.
- Added PowerShell export/import wrappers that refuse migration while the Gateway/service or port 8000 is active.
- Import applies service-owned ACL boundaries.

## Windows Service foundation

- Added a pywin32-based `AetherGateway` service host.
- Gateway stays bound to `127.0.0.1:8000`.
- Service state defaults to `C:\ProgramData\Aether`.
- Installer configures automatic start, SCM restart-on-failure, a virtual service identity, release read access, and mutable-state modify access.
- Uninstaller preserves mutable state.
- Actual Windows Server behavior remains pending VPS conformance.

## Verification

- Aether Core: 148 passed.
- Aether Tools: 52 passed, 1 optional skip.
- Modified cross-package regression slice: 37 passed.
- New Telegram presentation, Approval Inbox, migration snapshot, and service-host tests are included.
- Python compilation passed.
- Full Gateway single-process run still has the known long-lived FastAPI/process lifecycle hang; relevant modules are tested in isolated/targeted processes.
