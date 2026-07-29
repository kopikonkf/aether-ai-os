[CmdletBinding()]
param([string]$GatewayUrl = "http://127.0.0.1:8000")
Set-StrictMode -Version Latest
$service = Get-Service AetherGateway -ErrorAction SilentlyContinue
$health = $null
$errorText = $null
try { $health = Invoke-RestMethod -Uri "$GatewayUrl/api/status" -TimeoutSec 3 }
catch { $errorText = $_.Exception.Message }
[ordered]@{
    service_installed = [bool]$service
    service_status = if ($service) { [string]$service.Status } else { $null }
    service_start_type = if ($service) { [string]$service.StartType } else { $null }
    gateway_online = [bool]($health -and $health.status -eq "online")
    gateway_url = $GatewayUrl
    gateway_error = $errorText
    aether_home = [Environment]::GetEnvironmentVariable("AETHER_HOME", "Machine")
    release_root = [Environment]::GetEnvironmentVariable("AETHER_RELEASE_ROOT", "Machine")
} | ConvertTo-Json -Depth 5
