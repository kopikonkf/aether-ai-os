[CmdletBinding()]
param(
    [string]$ReleaseRoot = $PSScriptRoot,
    [string]$AetherHome = "C:\ProgramData\Aether",
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ReleaseRoot = [IO.Path]::GetFullPath($ReleaseRoot)
$AetherHome = [IO.Path]::GetFullPath($AetherHome)
$python = Join-Path $ReleaseRoot ".venv\Scripts\python.exe"
$serviceScript = Join-Path $ReleaseRoot "deploy\windows\aether_gateway_service.py"
if (-not (Test-Path $python -PathType Leaf)) { throw "Release Python not found: $python" }
if (-not (Test-Path $serviceScript -PathType Leaf)) { throw "Service host not found: $serviceScript" }

New-Item -ItemType Directory -Force -Path $AetherHome, (Join-Path $AetherHome "logs") | Out-Null
[Environment]::SetEnvironmentVariable("AETHER_HOME", $AetherHome, "Machine")
[Environment]::SetEnvironmentVariable("AETHER_RELEASE_ROOT", $ReleaseRoot, "Machine")
[Environment]::SetEnvironmentVariable("AETHER_LOG_ROOT", (Join-Path $AetherHome "logs"), "Machine")
$env:AETHER_HOME = $AetherHome
$env:AETHER_RELEASE_ROOT = $ReleaseRoot
$env:AETHER_LOG_ROOT = Join-Path $AetherHome "logs"

# pywin32 is an explicit Windows dependency of aether-gateway. Register the
# service through the exact release virtual environment.
& $python $serviceScript --startup auto install
if ($LASTEXITCODE -ne 0) { throw "AetherGateway service installation failed: $LASTEXITCODE" }

& sc.exe description AetherGateway "Aether AI OS Gateway and communication surfaces" | Out-Null
& sc.exe sidtype AetherGateway unrestricted | Out-Null
& sc.exe failure AetherGateway reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
& sc.exe failureflag AetherGateway 1 | Out-Null

# Use a virtual service identity instead of LocalSystem. No password is stored.
& sc.exe config AetherGateway obj= "NT SERVICE\AetherGateway" password= "" | Out-Null
& icacls $AetherHome /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "NT SERVICE\AetherGateway:(OI)(CI)M" | Out-Null
& icacls $ReleaseRoot /grant "NT SERVICE\AetherGateway:(OI)(CI)RX" | Out-Null

if ($Start) {
    Start-Service AetherGateway
    $deadline = (Get-Date).AddSeconds(60)
    do {
        Start-Sleep -Seconds 1
        try {
            $status = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/status" -TimeoutSec 3
            if ($status.status -eq "online") {
                Write-Host "AetherGateway service healthy."
                return
            }
        } catch { }
    } while ((Get-Date) -lt $deadline)
    throw "AetherGateway service started but health check did not become ready."
}

Get-Service AetherGateway | Select-Object Name, Status, StartType
