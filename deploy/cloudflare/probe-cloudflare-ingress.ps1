[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$TimeoutSeconds = 8,
    [string]$ServiceName = "AetherCloudflareTunnel",
    [ValidateSet("None", "Access", "CaddyBasic")]
    [string]$AuthMode = "None",
    [string]$AccessCookie = "",
    [string]$BasicUsername = "",
    [string]$BasicPassword = "",
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

# Cloudflare Access redirects unauthenticated clients to its own login host
# (https://<team-name>.cloudflareaccess.com/cdn-cgi/access/login/...) or, in
# some configurations, to a /.cloudflareaccess.com subdomain. A redirect is
# only accepted as proof of Access enforcement when the Location header points
# at that Cloudflare Access surface. Any other 3xx (an application redirect)
# is NOT proof that Access enforced anything.
function Test-AetherAccessProtected {
    param(
        [int]$StatusCode = 0,
        [string]$Location = ""
    )

    $denial = @(401, 403) -contains $StatusCode
    if ($denial) {
        return $true
    }

    if (-not ($StatusCode -ge 300 -and $StatusCode -le 399)) {
        return $false
    }

    if (-not $Location) {
        return $false
    }

    $locationHost = $null
    try {
        $locationHost = [Uri]$Location
    }
    catch {
        return $false
    }
    if ($null -eq $locationHost -or -not $locationHost.IsAbsoluteUri) {
        return $false
    }

    $hostName = $locationHost.Host.ToLowerInvariant()
    return (
        $hostName.EndsWith(".cloudflareaccess.com") -or
        $hostName -eq "cloudflareaccess.com" -or
        $locationHost.AbsolutePath.ToLowerInvariant().Contains("/cdn-cgi/access/")
    )
}

function Invoke-AetherProbeRoute {
    param(
        [Parameter(Mandatory = $true)][string]$Route,
        [string]$Cookie = "",
        [string]$BasicUsername = "",
        [string]$BasicPassword = ""
    )

    $started = Get-Date
    $statusCode = $null
    $ok = $false
    $redirected = $false
    $denied = $false
    $err = $null
    $location = $null

    $headers = @{}
    if ($Cookie) {
        $headers["Cookie"] = "CF_Authorization=$Cookie"
    }
    if ($BasicUsername) {
        $pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${BasicUsername}:${BasicPassword}"))
        $headers["Authorization"] = "Basic $pair"
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
    $denied = @(401, 403) -contains $statusCode
    $accessProtected = Test-AetherAccessProtected -StatusCode $statusCode -Location $location
    $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)

    return [ordered]@{
        path = $Route
        status_code = $statusCode
        ok = $ok
        redirected = $redirected
        denied = $denied
        access_protected = $accessProtected
        redirect_location = $location
        latency_ms = $latencyMs
        error = $err
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceStatus = if ($null -eq $service) { "missing" } else { $service.Status.ToString() }
$publicHttps = $base.StartsWith("https://")

# Unauthenticated probe (no credentials). Expect the auth surface to deny all
# routes. For Access this is a redirect/401/403; for CaddyBasic it must be 401.
$unauthenticatedRoutes = @(
    foreach ($route in $requiredRoutes) {
        Invoke-AetherProbeRoute -Route $route
    }
)

if ($AuthMode -eq "CaddyBasic") {
    $unauthenticatedAllProtected = (
        ($unauthenticatedRoutes | Where-Object { -not $_.denied }).Count -eq 0
    )
}
else {
    $unauthenticatedAllProtected = (
        ($unauthenticatedRoutes | Where-Object { -not $_.access_protected }).Count -eq 0
    )
}

# Authenticated probe: real credentials must return the Aether app (2xx).
$authenticatedRoutes = @()
if ($AuthMode -eq "Access" -and $AccessCookie) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Cookie $AccessCookie
        }
    )
}
elseif ($AuthMode -eq "CaddyBasic" -and $BasicUsername) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -BasicUsername $BasicUsername -BasicPassword $BasicPassword
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
elseif ($AuthMode -eq "CaddyBasic") {
    $unauthenticatedAllProtected -and $authenticatedAllOk
}
elseif ($AccessCookie) {
    $authenticatedAllOk
}
else {
    $unauthenticatedAllProtected
}

$status = if (
    $requiredOk -and
    $publicHttps -and
    $serviceStatus -eq "Running" -and
    -not ($AuthMode -eq "CaddyBasic" -and -not $unauthenticatedAllProtected)
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
    auth_mode = $AuthMode
    auth_scope = "all_paths"
    mode = if ($AuthMode -eq "CaddyBasic") { "caddy-basic" } elseif ($ExpectAccessEnforcement) { "access-enforcement" } elseif ($AccessCookie) { "authenticated" } else { "unauthenticated" }
    required_routes = $requiredRoutes
    required_routes_ok = $requiredOk
    unauthenticated_routes = $unauthenticatedRoutes
    unauthenticated_all_denied = $unauthenticatedAllProtected
    authenticated_routes = $authenticatedRoutes
    authenticated_all_ok = $authenticatedAllOk
    authorization_forwarded_to_upstream = $false
    secret_values_exposed = $false
}

$json = $receipt | ConvertTo-Json -Depth 8 -Compress
$json | Set-Content -LiteralPath $latestPath -Encoding UTF8
Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8
