param(
    [Parameter(Mandatory = $true)]
    [string]$LegacyBrainRoot,
    [string]$ReleaseRoot = (Get-Location).Path,
    [switch]$Apply,
    [string]$Output = ""
)
$ErrorActionPreference = "Stop"
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Aether virtualenv Python not found: $python" }
$script = Join-Path $ReleaseRoot "scripts\aether_state_continuity.py"
$argsList = @($script, "--release-root", $ReleaseRoot, "migrate-legacy", "--source", $LegacyBrainRoot)
if ($Apply) { $argsList += "--apply" }
if ($Output) { $argsList += @("--output", $Output) }
& $python @argsList
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
