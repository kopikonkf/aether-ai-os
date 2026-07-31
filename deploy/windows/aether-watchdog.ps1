[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [string[]]$ServiceNames = @("AetherGateway"),
    [int]$IntervalSeconds = 30,
    [int]$TimeoutSeconds = 5,
    [int]$MaxFailures = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$servicesDir = Join-Path $AetherHome "services"
New-Item -ItemType Directory -Force -Path $servicesDir | Out-Null
$heartbeatPath = Join-Path $servicesDir "heartbeats.jsonl"

function Write-AetherHeartbeat {
    param([hashtable]$Event)

    $Event["observed_at"] = (Get-Date).ToUniversalTime().ToString("o")
    $line = $Event | ConvertTo-Json -Depth 10 -Compress
    Add-Content -LiteralPath $heartbeatPath -Value $line -Encoding UTF8
}

$consecutiveFailures = 0

Write-AetherHeartbeat @{
    event = "watchdog.started"
    health_url = $HealthUrl
    services = $ServiceNames
    max_failures = $MaxFailures
    interval_seconds = $IntervalSeconds
}

while ($true) {
    $serviceStates = @{}
    $errors = @()
    $action = "none"

    foreach ($name in $ServiceNames) {
        $service = Get-Service -Name $name -ErrorAction SilentlyContinue
        if ($null -eq $service) {
            $serviceStates[$name] = "missing"
            $errors += "service missing: $name"
            continue
        }

        $serviceStates[$name] = $service.Status.ToString()
        if ($service.Status -ne "Running") {
            try {
                Start-Service -Name $name -ErrorAction Stop
                $action = "start:$name"
                Start-Sleep -Seconds 2
                $serviceStates[$name] = (Get-Service -Name $name).Status.ToString()
            }
            catch {
                $errors += "start failed for $name: $($_.Exception.Message)"
            }
        }
    }

    $healthOk = $false
    $latencyMs = $null
    $healthPayload = $null
    $started = Get-Date

    try {
        $healthPayload = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec $TimeoutSeconds -Method Get
        $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)
        $healthOk = ($healthPayload.status -in @("ok", "online"))
    }
    catch {
        $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)
        $errors += "health failed: $($_.Exception.Message)"
    }

    if ($healthOk) {
        $consecutiveFailures = 0
    }
    else {
        $consecutiveFailures += 1
    }

    if (-not $healthOk -and $consecutiveFailures -ge $MaxFailures) {
        try {
            Restart-Service -Name "AetherGateway" -Force -ErrorAction Stop
            $action = "restart:AetherGateway"
            $consecutiveFailures = 0
        }
        catch {
            $errors += "restart failed for AetherGateway: $($_.Exception.Message)"
        }
    }

    Write-AetherHeartbeat @{
        event = "watchdog.heartbeat"
        health_url = $HealthUrl
        health_ok = $healthOk
        health_latency_ms = $latencyMs
        health = $healthPayload
        services = $serviceStates
        consecutive_failures = $consecutiveFailures
        action = $action
        errors = $errors
    }

    Start-Sleep -Seconds $IntervalSeconds
}