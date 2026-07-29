[CmdletBinding()]
param([string]$ReleaseRoot = $PSScriptRoot)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ReleaseRoot = [IO.Path]::GetFullPath($ReleaseRoot)
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
$serviceScript = Join-Path $ReleaseRoot "deploy\windows\aether_gateway_service.py"
$service = Get-Service AetherGateway -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "AetherGateway service is not installed."
    return
}
if ($service.Status -ne "Stopped") {
    Stop-Service AetherGateway -Force
    $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
}
& $python $serviceScript remove
if ($LASTEXITCODE -ne 0) { throw "AetherGateway service removal failed: $LASTEXITCODE" }
Write-Host "AetherGateway service removed. Mutable AETHER_HOME state was preserved."
