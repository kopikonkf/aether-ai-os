[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$TimeoutSeconds = 8,
    [string]$ServiceName = "AetherCloudflareTunnel"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$requiredRoutes = @("/health", "/aether/api/status", "/api/browser-senses/status", "/senses")
$runtimeDir = Join-Path $AetherHome "runtime"
$ingressDir = Join-Path $runtimeDir "ingress"
New-Item -ItemType Directory -Force -Path $runtimeDir, $ingressDir | Out-Null
$latestPath = Join-Path $ingressDir "latest_cloudflare_probe.json"
$logPath = Join-Path $ingressDir "cloudflare-probes.jsonl"

$base = $BaseUrl.TrimEnd("/")
$routes = @()
foreach ($route in $requiredRoutes) {
    $started = Get-Date
    $statusCode = $null
    $ok = $false
    $err = $null
    try {
        $response = Invoke-WebRequest -Uri "$base$route" -TimeoutSec $TimeoutSeconds -UseBasicParsing -MaximumRedirection 0
        $statusCode = [int]$response.StatusCode
        $ok = ($statusCode -ge 200 -and $statusCode -lt 300)
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        $err = $_.Exception.GetType().Name
    }
    $redirected = @(302, 303, 307, 308) -contains $statusCode
    if ($redirected) {
        $ok = $false
        $err = "Access-redirect-or-auth-required"
    }
    $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)
    $routes += [ordered]@{
        path = $route
        status_code = $statusCode
        ok = $ok
        redirected = $redirected
        latency_ms = $latencyMs
        error = $err
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceStatus = if ($null -eq $service) { "missing" } else { $service.Status.ToString() }
$requiredOk = (($routes | Where-Object { -not $_.ok }).Count -eq 0)
$publicHttps = $base.StartsWith("https://")
$status = if ($requiredOk -and $publicHttps -and $serviceStatus -eq "Running") { "ok" } else { "fail" }

$receipt = [ordered]@{
    schema = "aether.cloudflare-ingress.v1"
    event = "cloudflare.ingress.probed"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    status = $status
    base_url = $base
    public_https = $publicHttps
    cloudflare_tunnel = ($serviceStatus -eq "Running")
    cloudflared_service_status = $serviceStatus
    required_routes = $requiredRoutes
    required_routes_ok = $requiredOk
    routes = $routes
    receipt_source = "probe-cloudflare-ingress.ps1"
    secret_values_exposed = $false
}

$json = $receipt | ConvertTo-Json -Depth 8 -Compress
$json | Set-Content -LiteralPath $latestPath -Encoding UTF8
Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
