# Windows First-Boot Troubleshooting — v0.19.2 Overlay.2

## Observed errors

### `OSArchitecture cannot be found`

Cause: some Windows/CIM environments do not expose `Win32_OperatingSystem.OSArchitecture`.
This is a readiness-reporting defect, not an Aether Core crash.

Resolution: overlay.2 falls back to .NET RuntimeInformation architecture.

### `py.exe: No suitable Python runtime found`

Cause: the Windows Python launcher exists, but no compatible Python interpreter is installed.
Aether v0.19.2 requires Python 3.11 or newer.

## Required recovery sequence

1. Install 64-bit Python 3.11 or newer.
2. Enable the Python launcher and/or add Python to PATH.
3. Close all PowerShell windows.
4. Open a new PowerShell window.
5. Verify:

```powershell
py -0p
py -3.11 --version
```

If the second command does not work but `python --version` reports 3.11 or newer, the patched launcher will use `python`.

6. Rerun:

```powershell
cd C:\Aether\Aether_OS_v0.19.2-unified-browser-senses
Set-ExecutionPolicy -Scope Process Bypass
.\AETHER_WINDOWS_READINESS.ps1
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
```

## `.bat` files

Do not use the original overlay.1 `.bat` files before installing Python. They invoked the system `python` command directly.

Overlay.2 changes them:

- `FIRST_PULSE.bat` delegates to the corrected PowerShell launcher with `-Action Pulse`.
- `START_AETHER.bat` delegates to the corrected PowerShell launcher with `-Action Start`.

For first boot, the canonical command remains:

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action All
```

Use the `.bat` launchers only after first boot succeeds.
