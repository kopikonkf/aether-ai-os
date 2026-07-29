> **Frozen.2 hotfix:** Frozen.1 could report doctor failure even when doctor returned `base_ready: true` and exit code `0`, because PowerShell captured JSON stdout together with the exit code. Frozen.2 separates those channels.

# Aether OS v0.19.2 Founder Alpha — Frozen Laptop Baseline

**Build ID:** `v0.19.2-founder-alpha-frozen.2`

This is the single full release that freezes the Windows-laptop validation phase. It supersedes all earlier sliced overlays and consolidated `.1`/`.2` candidates. Do not stack previous ZIPs on top of this folder.

## Included and wired

- complete Aether Core, Gateway, and Tools source;
- rebuilt wheels from this exact source tree;
- approved persona v3;
- Browser Senses text, camera, and browser speech fallback;
- tool preflight, exact-once approval, no automatic failed-action retry;
- deterministic write receipts with path, byte count, disposition, and SHA-256;
- Telegram one-tap approval card:

```text
[ ✅ Approve once ] [ ❌ Reject ]
[ 🔍 Details ]
```

- central Telegram `CommandRegistry` and generated command menu;
- `/yes`, `/no`, `/approvals`, and explicit ID fallbacks;
- persistent trust-observation epoch across Gateway restarts;
- Windows PowerShell OS-description/architecture fallbacks;
- state inspector schema v2 covering all composition-root stores;
- original-brain inert archive boundary: preserve and hash, never bulk inject;
- live Telegram read/write proof and capability wiring utilities.

Google TTS, Agent-Reach, Windows persistent services, Cloudflare public ingress, and a conformed coding runtime body remain later operational gates. They are not silently claimed by this baseline.

## Upgrade once from the current consolidated.1 folder

Keep the working installation as rollback evidence:

```text
C:\Aether\Aether_OS_v0.19.2-founder-alpha-consolidated.1\
C:\Aether\Aether_OS_v0.19.2-founder-alpha-frozen.2\
```

Open a new PowerShell window:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd C:\Aether\Aether_OS_v0.19.2-founder-alpha-frozen.2

.\MIGRATE_EXISTING_WINDOWS_RELEASE.ps1 `
  -OldReleaseRoot C:\Aether\Aether_OS_v0.19.2-founder-alpha-consolidated.1

.\AETHER_WINDOWS_READINESS.ps1
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Status
.\AETHER_STATE_INSPECT.ps1 `
  -Output "$env:LOCALAPPDATA\Aether\runtime_state\reports\laptop-baseline-freeze-v2.json"
```

The migration helper copies only `aether-core\.env`. Mutable state remains under the existing `AETHER_HOME`; it does not copy `.venv`, PID state, or SQLite files between release folders.

Expected build ID:

```text
v0.19.2-founder-alpha-frozen.2
```

## Founder acceptance: one-tap write and automatic read

Ask Aether in Telegram:

```text
Aether, buat file workspace/frozen-baseline-proof.md.
Tuliskan satu paragraf bahwa laptop baseline v0.19.2 telah dibekukan.
Gunakan tool write dan setelah selesai tampilkan authoritative receipt saja.
```

Tap **Approve once**. The edited approval card must show `completed`, the resolved path, byte size, disposition, and SHA-256, with no stale waiting message.

Then ask:

```text
Aether, baca workspace/frozen-baseline-proof.md dan tampilkan isi persisnya tanpa parafrase.
```

`read` is bounded and read-only, so it should execute without manual approval.

## Slash commands

The Telegram menu is generated from the same registry used to bind handlers:

```text
/start
/help
/new
/clear
/status
/model
/approvals
/yes
/no
```

Explicit machine/audit fallbacks remain available but hidden from the menu:

```text
/approve <approval_id> [reason]
/reject <approval_id> [reason]
```

No command is exposed until its handler is wired.

## Original brain boundary

Do not inject the old brain into current memory or Obsidian. Dry-run first:

```powershell
.\MIGRATE_LEGACY_AETHER_BRAIN.ps1 `
  -LegacyBrainRoot C:\path\to\extracted\hermes-brain
```

`-Apply` creates an inert archive under:

```text
%AETHER_HOME%\legacy\archives\original-brain\<import-id>
```

It does **not** insert files into current memory, Skill Factory, governed knowledge, workspace, or the live Obsidian vault. Potential-secret files are hash-reported only and are not copied.

## Freeze rule

After the acceptance proof passes, do not continue feature work on the laptop installation. Keep this folder and an encrypted/protected `AETHER_HOME` backup as rollback evidence. The next target is the Windows VPS.
