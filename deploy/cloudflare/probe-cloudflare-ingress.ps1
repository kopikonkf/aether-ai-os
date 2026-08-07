[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$TimeoutSeconds = 8,
    [string]$ServiceName = "AetherCloudflareTunnel",
    [ValidateSet("None", "Access", "CaddyBasic")]
    [string]$AuthMode = "None",
    [string]$AccessCookie = "",
    [System.Management.Automation.PSCredential]$Credential = $null,
    [System.Management.Automation.PSCredential]$WrongCredential = $null,
    [string]$CaddyAdminUrl = "http://127.0.0.1:2019",
    [switch]$ExpectAccessEnforcement
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($AuthMode -eq "CaddyBasic" -and $ExpectAccessEnforcement) {
    throw "ExpectAccessEnforcement is Access-only; reject conflicting flags for CaddyBasic."
}
if ($AuthMode -eq "None" -and ($AccessCookie -or $Credential -or $ExpectAccessEnforcement)) {
    throw "AuthMode=None rejects credential/access flags; they cannot be combined."
}

$requiredRoutes = @("/health", "/aether/api/status", "/api/browser-senses/status", "/senses")
$runtimeDir = Join-Path $AetherHome "runtime"
$ingressDir = Join-Path $runtimeDir "ingress"
New-Item -ItemType Directory -Force -Path $runtimeDir, $ingressDir | Out-Null
$latestPath = Join-Path $ingressDir "latest_cloudflare_probe.json"
$logPath = Join-Path $ingressDir "cloudflare-probes.jsonl"

$base = $BaseUrl.TrimEnd("/")

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
        [System.Management.Automation.PSCredential]$Cred = $null
    )

    $started = Get-Date
    $statusCode = $null
    $ok = $false
    $redirected = $false
    $err = $null
    $location = $null
    $wwwAuthenticate = $null

    $headers = @{}
    if ($Cookie) {
        $headers["Cookie"] = "CF_Authorization=$Cookie"
    }
    if ($null -ne $Cred) {
        $pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$($Cred.UserName):$($Cred.GetNetworkCredential().Password)"))
        $headers["Authorization"] = "Basic $pair"
    }

    try {
        $response = Invoke-WebRequest -Uri "$base$Route" -TimeoutSec $TimeoutSeconds -UseBasicParsing -MaximumRedirection 0 -Headers $headers
        $statusCode = [int]$response.StatusCode
        $ok = ($statusCode -ge 200 -and $statusCode -lt 300)
        if ($response.Headers["WWW-Authenticate"]) {
            $wwwAuthenticate = $response.Headers["WWW-Authenticate"]
        }
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($_.Exception.Response -and $_.Exception.Response.Headers) {
            $location = $_.Exception.Response.Headers["Location"]
            $wwwAuthenticate = $_.Exception.Response.Headers["WWW-Authenticate"]
        }
        $err = $_.Exception.GetType().Name
    }

    $redirected = @(301, 302, 303, 307, 308) -contains $statusCode
    $denied = @(401, 403) -contains $statusCode
    $basicChallenge = (
        $statusCode -eq 401 -and
        $wwwAuthenticate -and
        $wwwAuthenticate -match "(?i)basic"
    )
    $accessProtected = Test-AetherAccessProtected -StatusCode $statusCode -Location $location
    $latencyMs = [math]::Round(((Get-Date) - $started).TotalMilliseconds, 1)

    return [ordered]@{
        path = $Route
        status_code = $statusCode
        ok = $ok
        redirected = $redirected
        denied = $denied
        basic_challenge = $basicChallenge
        www_authenticate = $wwwAuthenticate
        access_protected = $accessProtected
        redirect_location = $location
        latency_ms = $latencyMs
        error = $err
    }
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$serviceStatus = if ($null -eq $service) { "missing" } else { $service.Status.ToString() }
$publicHttps = $base.StartsWith("https://")

$unauthenticatedRoutes = @(
    foreach ($route in $requiredRoutes) {
        Invoke-AetherProbeRoute -Route $route
    }
)

if ($AuthMode -eq "CaddyBasic") {
    $unauthenticatedAllDenied = (
        ($unauthenticatedRoutes | Where-Object { -not $_.basic_challenge }).Count -eq 0
    )
}
else {
    $unauthenticatedAllDenied = (
        ($unauthenticatedRoutes | Where-Object { -not $_.access_protected }).Count -eq 0
    )
}

$authenticatedRoutes = @()
if ($AuthMode -eq "Access" -and $AccessCookie) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Cookie $AccessCookie
        }
    )
}
elseif ($AuthMode -eq "CaddyBasic" -and $null -ne $Credential) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Cred $Credential
        }
    )
}
$authenticatedAllOk = (
    $authenticatedRoutes.Count -gt 0 -and
    ($authenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
)

$invalidRoutes = @()
if ($AuthMode -eq "CaddyBasic" -and $null -ne $WrongCredential) {
    $invalidRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Cred $WrongCredential
        }
    )
}
$invalidCredentialsAllDenied = (
    $invalidRoutes.Count -gt 0 -and
    ($invalidRoutes | Where-Object { -not $_.basic_challenge }).Count -eq 0
)

$headerStripped = $false
$caddyConfigChecked = $false
try {
    $cfg = Invoke-RestMethod -Uri "$CaddyAdminUrl/config/" -TimeoutSec 8
    $cfgJson = $cfg | ConvertTo-Json -Depth 20
    $headerStripped = (
        $cfgJson -match '"-Authorization"' -or
        $cfgJson -match "header_up" -and $cfgJson -match "Authorization"
    )
    $caddyConfigChecked = $true
}
catch {
    $caddyConfigChecked = $false
}

$requiredOk = switch ($AuthMode) {
    "CaddyBasic" {
        $unauthenticatedAllDenied -and
        $authenticatedAllOk -and
        $invalidCredentialsAllDenied
    }
    "Access" {
        if ($ExpectAccessEnforcement) {
            $unauthenticatedAllDenied
        }
        elseif ($AccessCookie) {
            $authenticatedAllOk
        }
        else {
            $unauthenticatedAllDenied
        }
    }
    default {
        ($unauthenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
    }
}

$status = if (
    $requiredOk -and
    $publicHttps -and
    $serviceStatus -eq "Running" -and
    $caddyConfigChecked -and
    $headerStripped
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
    mode = if ($AuthMode -eq "CaddyBasic") { "caddy-basic" } elseif ($ExpectAccessEnforcement) { "access-enforcement" } else { $AuthMode.ToLower() }
    required_routes = $requiredRoutes
    required_routes_ok = $requiredOk
    unauthenticated_routes = $unauthenticatedRoutes
    unauthenticated_all_denied = $unauthenticatedAllDenied
    authenticated_routes = $authenticatedRoutes
    authenticated_all_ok = $authenticatedAllOk
    invalid_credentials_routes = $invalidRoutes
    invalid_credentials_all_denied = $invalidCredentialsAllDenied
    authorization_forwarded_to_upstream = (-not $headerStripped)
    caddy_config_checked = $caddyConfigChecked
    secret_values_exposed = $false
}

$json = $receipt | ConvertTo-Json -Depth 10 -Compress
$json | Set-Content -LiteralPath $latestPath -Encoding UTF8
Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8
$receipt | ConvertTo-Json -Depth 10
