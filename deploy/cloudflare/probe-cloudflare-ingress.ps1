[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$TimeoutSeconds = 8,
    [string]$ServiceName = "AetherCloudflareTunnel",
    [string]$AccessCookie = "",
    [switch]$ExpectAccessEnforcement
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

function Invoke-AetherProbeRoute {
    param(
        [Parameter(Mandatory = $true)][string]$Route,
        [string]$Cookie = ""
    )

    $started = Get-Date
    $statusCode = $null
    $ok = $false
    $redirected = $false
    $err = $null
    $location = $null

    $headers = @{}
    if ($Cookie) {
        $headers["Cookie"] = "CF_Authorization=$Cookie"
    }

    try {
        $response = Invoke-WebRequest -Uri "$base$Route" -TimeoutSec $TimeoutSeconds -UseBasicParsing -MaximumRedirection 0 -Headers $headers
        $statusCode = [int]$response.StatusCode
        $ok = ($statusCode -ge 200 -and $statusCode -lt 300)
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($_.Exception.Response -and $_.Exception.Response.Headers) {
            $location = $_.Exception.Response.Headers["Location"]
        }
        $err = $_.Exception.GetType().Name
    }

    $redirected = @(301, 302, 303, 307, 308) -contains $statusCode
    $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)

    return [ordered]@{
        path = $Route
        status_code = $statusCode
        ok = $ok
        redirected = $redirected
        redirect_location = $location
        latency_ms = $latencyMs
        error = $err
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceStatus = if ($null -eq $service) { "missing" } else { $service.Status.ToString() }
$publicHttps = $base.StartsWith("https://")

# Mode 1: unauthenticated probe (no cookie). With Cloudflare Access enabled,
# every public route must be redirected/denied, never served anonymously.
$unauthenticatedRoutes = @(
    foreach ($route in $requiredRoutes) {
        Invoke-AetherProbeRoute -Route $route
    }
)
$unauthenticatedAllProtected = (
    ($unauthenticatedRoutes | Where-Object { -not $_.redirected }).Count -eq 0
)

# Mode 2: authenticated probe (Access session cookie). Routes must return the
# real Aether application (2xx), proving they are reachable behind Access.
$authenticatedRoutes = @()
if ($AccessCookie) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Cookie $AccessCookie
        }
    )
}
$authenticatedAllOk = (
    $authenticatedRoutes.Count -gt 0 -and
    ($authenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
)

$requiredOk = if ($ExpectAccessEnforcement) {
    $unauthenticatedAllProtected
}
elseif ($AccessCookie) {
    $authenticatedAllOk
}
else {
    ($unauthenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
}

$status = if (
    $requiredOk -and
    $publicHttps -and
    $serviceStatus -eq "Running" -and
    -not ($ExpectAccessEnforcement -and -not $unauthenticatedAllProtected)
) {
    "ok"
}
else {
    "fail"
}

$receipt = [ordered]@{
    schema = "aether.cloudflare-ingress.v1"
    event = "cloudflare.ingress.probed"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    status = $status
    base_url = $base
    public_https = $publicHttps
    cloudflare_tunnel = ($serviceStatus -eq "Running")
    cloudflared_service_status = $serviceStatus
    mode = if ($ExpectAccessEnforcement) { "access-enforcement" } elseif ($AccessCookie) { "authenticated" } else { "unauthenticated" }
    required_routes = $requiredRoutes
    required_routes_ok = $requiredOk
    unauthenticated_routes = $unauthenticatedRoutes
    unauthenticated_all_protected = $unauthenticatedAllProtected
    authenticated_routes = $authenticatedRoutes
    authenticated_all_ok = $authenticatedAllOk
    access_cookie_present = [bool]$AccessCookie
    receipt_source = "probe-cloudflare-ingress.ps1"
    secret_values_exposed = $false
}

$json = $receipt | ConvertTo-Json -Depth 8 -Compress
$json | Set-Content -LiteralPath $latestPath -Encoding UTF8
Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
