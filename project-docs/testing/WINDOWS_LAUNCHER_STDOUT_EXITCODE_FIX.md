# Windows launcher stdout / exit-code separation

## Symptom

`START_AETHER_WINDOWS_ALPHA.ps1 -Action All` printed a healthy doctor JSON ending in `base_ready: true`, followed by `0`, but then threw:

```text
Aether doctor failed with exit code { ...doctor JSON... } 0
```

## Root cause

PowerShell functions emit every success-stream object. `Invoke-Bringup` emitted the Python doctor's JSON stdout and then returned `$LASTEXITCODE`. Assigning the function call to `$code` therefore produced an array containing both the JSON output and integer `0`. The comparison `$code -ne 0` evaluated true.

## Correction

- Child stdout remains visible to the operator.
- Process exit status is stored separately in `$script:LastBringupExitCode`.
- `Init`, `Doctor`, and `Smoke` inspect only that integer.
- The migration helper stops an old Gateway directly through its PID file instead of invoking an older launcher's status renderer.

## Safe recovery for frozen.1

```powershell
.\START_AETHER_WINDOWS_ALPHA.ps1 -Action Start
```

This bypasses the broken Doctor wrapper and starts the already-installed Gateway. The permanent correction is shipped in `v0.19.2-founder-alpha-frozen.2`.
