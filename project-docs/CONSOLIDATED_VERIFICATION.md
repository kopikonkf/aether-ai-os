# Frozen Laptop Baseline Verification

**Build:** `v0.19.2-founder-alpha-frozen.2`  
**Date:** 2026-07-29

## Test evidence

```text
Aether Core full suite:                         148 passed
Aether Tools full suite:                         52 passed, 1 optional skip
Aether Gateway complete collection (frozen.1 source): 97 passed
Current approval/command/deployment slice:             21 passed
Windows launcher contract verifier:                    7 passed
Python source compilation:                       passed
JSON parsing:                                     23 files passed
YAML parsing:                                     52 files passed
Browser Senses JavaScript syntax:                passed
State inspector v2 on uploaded AETHER_HOME:      passed
Original-brain preservation v2 dry-run:          passed
Wheel build:                                       3 passed
Wheel import/package-data smoke:                 passed
```

Gateway tests were executed one test module per fresh process. Several modules import the global FastAPI composition root or create subprocess/lifespan state; isolation prevents cross-module state contamination while still executing all 97 collected tests.

## Verified freeze behaviors

- signed compact Telegram callback payloads fit Telegram's callback limit;
- callback tampering is rejected;
- approval is bound to trusted Founder and originating chat;
- Details does not consume approval;
- Approve/Reject consumes the exact action at most once;
- command menu, help, and handlers come from one registry;
- startup rejects a command whose handler is missing;
- successful writes return deterministic disk-backed receipts without a second model generation;
- impossible paths fail before approval;
- failed approved actions do not enter automatic approval loops;
- trust observation epoch persists and malformed state is repaired;
- Windows status uses reflection/CIM/environment fallbacks;
- state inspector v2 covers 19 known SQLite authorities and safe behavior state;
- original-brain preservation creates an inert archive and authorizes zero automatic semantic imports;
- potential-secret files are hash-only and not copied.

## Wheel SHA-256

```text
bdb9864f292a064732a557ab17393c43aab83a6e5e4445f7b09b53cdaecef869  aether_core-0.19.2-py3-none-any.whl
651a539bd12b152172a2704e79b0ae52b848cb3d7d49e6b89360533449a62c44  aether_tools-0.3.0-py3-none-any.whl
3f5dfa5adf876311eaa44684c6e15219c11fe5402d7a07dba84c20d51311aa3c  aether_gateway-0.19.2-py3-none-any.whl
```

## Environment boundary

The build container is Linux. PowerShell source and fallback contracts are covered by static contract verification, but the final ZIP has not been executed by this environment on Windows. Frozen.2 specifically corrects a Windows PowerShell success-stream bug where doctor JSON stdout and integer exit status were captured into the same variable. The Founder acceptance sequence in `START_HERE_CONSOLIDATED.md` is therefore the final freeze gate.

## Frozen.2 launcher hotfix

- Doctor JSON stdout remains visible and is never used as an exit-code value.
- `Init`, `Doctor`, and `Smoke` read a dedicated integer process status.
- A healthy doctor result ending in `base_ready: true` and exit code `0` proceeds to Smoke and Gateway Start.
- Migration stops the previous Gateway directly from `.aether-windows\gateway.pid`, avoiding legacy status-renderer defects.
- Frozen.1 emergency recovery remains `./START_AETHER_WINDOWS_ALPHA.ps1 -Action Start`.
