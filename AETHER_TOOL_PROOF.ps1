param(
    [ValidateSet("Create", "Verify")]
    [string]$Action = "Create",
    [string]$ReleaseRoot = (Get-Location).Path
)
$ErrorActionPreference = "Stop"
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Aether virtualenv Python not found: $python" }
$script = Join-Path $ReleaseRoot "scripts\aether_state_continuity.py"
$command = if ($Action -eq "Create") { "create-tool-proof" } else { "verify-tool-proof" }
& $python $script --release-root $ReleaseRoot $command
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
