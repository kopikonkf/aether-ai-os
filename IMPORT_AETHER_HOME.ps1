[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Snapshot,
    [string]$AetherHome = $env:AETHER_HOME,
    [string]$ReleaseRoot = $PSScriptRoot,
    [switch]$AllowNonEmpty
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $AetherHome) { $AetherHome = "C:\ProgramData\Aether" }
$AetherHome = [IO.Path]::GetFullPath($AetherHome)
$Snapshot = [IO.Path]::GetFullPath($Snapshot)
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
$helper = Join-Path $ReleaseRoot "scripts\aether_home_snapshot.py"

$service = Get-Service -Name "AetherGateway" -ErrorAction SilentlyContinue
if ($service -and $service.Status -ne "Stopped") { throw "Stop AetherGateway before importing mutable state." }
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8000 still has a listener; import aborted."
}

$args = @($helper, "import", "--snapshot", $Snapshot, "--destination", $AetherHome)
if ($AllowNonEmpty) { $args += "--allow-nonempty" }
& $python @args
if ($LASTEXITCODE -ne 0) { throw "AETHER_HOME import failed with exit code $LASTEXITCODE" }

& icacls $AetherHome /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
if ($service) {
    $serviceIdentity = "NT SERVICE\AetherGateway"
    & icacls $AetherHome /grant "$serviceIdentity`:(OI)(CI)M" | Out-Null
}
Write-Host "Imported AETHER_HOME and applied service ACLs: $AetherHome"
