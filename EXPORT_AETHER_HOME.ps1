[CmdletBinding()]
param(
    [string]$AetherHome = $env:AETHER_HOME,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$ReleaseRoot = $PSScriptRoot,
    [switch]$StopGateway
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $AetherHome) {
    $AetherHome = Join-Path $env:LOCALAPPDATA "Aether"
}
$AetherHome = [IO.Path]::GetFullPath($AetherHome)
$Output = [IO.Path]::GetFullPath($Output)
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
$helper = Join-Path $ReleaseRoot "scripts\aether_home_snapshot.py"

if (-not (Test-Path $AetherHome -PathType Container)) { throw "AETHER_HOME not found: $AetherHome" }
if (-not (Test-Path $python -PathType Leaf)) { throw "Release Python not found: $python" }
if (-not (Test-Path $helper -PathType Leaf)) { throw "Snapshot helper not found: $helper" }

$service = Get-Service -Name "AetherGateway" -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne "Stopped") {
    if (-not $StopGateway) { throw "AetherGateway service is running. Re-run with -StopGateway." }
    Stop-Service -Name "AetherGateway" -Force
    $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}

$pidFile = Join-Path $ReleaseRoot ".aether-windows\gateway.pid"
if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile -Raw).Trim()
    if ($pidValue -match '^\d+$' -and (Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue)) {
        if (-not $StopGateway) { throw "Founder-alpha Gateway process is running. Re-run with -StopGateway." }
        & (Join-Path $ReleaseRoot "START_AETHER_WINDOWS_ALPHA.ps1") -Action Stop
    }
}

$listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listeners) { throw "Port 8000 still has a listener; snapshot aborted." }

& $python $helper export --source $AetherHome --output $Output
if ($LASTEXITCODE -ne 0) { throw "AETHER_HOME export failed with exit code $LASTEXITCODE" }
