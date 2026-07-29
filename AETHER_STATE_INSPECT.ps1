param(
    [string]$ReleaseRoot = (Get-Location).Path,
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Aether virtualenv Python not found: $python" }
$script = Join-Path $ReleaseRoot "scripts\aether_state_continuity.py"
if (-not (Test-Path $script)) { throw "State continuity script not found: $script" }
$argsList = @($script, "--release-root", $ReleaseRoot, "inspect")
if ($Output) { $argsList += @("--output", $Output) }
& $python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
