[CmdletBinding()]
param(
    [switch]$RemoveRuntimeState
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$services = @("AetherWatchdog", "AetherSenseWorker", "AetherGateway")

foreach ($name in $services) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        continue
    }

    if ($service.Status -ne "Stopped") {
        Stop-Service -Name $name -Force -ErrorAction SilentlyContinue
        $service.WaitForStatus("Stopped", "00:00:20")
    }

    sc.exe delete $name | Out-Null
}

if ($RemoveRuntimeState) {
    Write-Warning "Runtime state deletion is intentionally not automated. Remove C:\ProgramData\Aether manually only after backup and Founder approval."
}

[ordered]@{
    status = "removed"
    services = $services
    runtime_state_preserved = $true
} | ConvertTo-Json -Depth 4