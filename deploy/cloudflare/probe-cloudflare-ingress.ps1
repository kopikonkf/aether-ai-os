[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [int]$TimeoutSeconds = 8,
    [string]$ServiceName = "AetherCloudflareTunnel",
    [ValidateSet("None", "Access", "CaddyBasic")]
    [string]$AuthMode = "None",
    [string]$AccessCookie = "",
    # Echo upstream route used to observe the actual headers the upstream
    # receives. When set in CaddyBasic mode the probe sends an authenticated
    # request through Caddy to this route and derives
    # `authorization_forwarded_to_upstream` from the JSON body the echo
    # upstream returns (its own received headers) - never from Caddy `/config/`.
    [string]$EchoRoute = "",
    # Credential source: an in-memory PSCredential (recommended, default) OR a
    # username whose password is read from stdin. Passwords are never accepted
    # as a command-line argument.
    [System.Management.Automation.PSCredential]$Credential,
    [string]$CredentialUsername = "",
    [switch]$CredentialPasswordStdin,
    [System.Management.Automation.PSCredential]$WrongCredential,
    [string]$WrongCredentialUsername = "",
    [switch]$WrongCredentialPasswordStdin,
    [switch]$ExpectAccessEnforcement
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Read-LineFromStdin {
    if ([Console]::IsInputRedirected) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) { return "" }
        return $line
    }
    return ""
}

function Convert-SecureStringToPlain {
    param(
        [Parameter(Mandatory = $true)][System.Security.SecureString]$SecureString
    )
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

# ---- Credential resolution (secret-safe) -------------------------------------
# Both a correct and an optional wrong credential surface may be supplied.
# Each resolves to a plaintext password at runtime from a PSCredential object or
# from stdin. A command-line password parameter does not exist.

function Resolve-CredentialPair {
    param(
        [string]$Label,
        [System.Management.Automation.PSCredential]$Object,
        [string]$Username,
        [switch]$FromStdin
    )

    if ($null -ne $Object) {
        if ($Username) {
            throw "Invalid $Label credential: supply -${Label} and -${Label}Username, not both."
        }
        if ($FromStdin) {
            throw "Invalid $Label credential: supply -${Label} (object) and -${Label}PasswordStdin, not both."
        }
        return [ordered]@{
            username = $Object.UserName
            password = (Convert-SecureStringToPlain $Object.Password)
            present  = $true
        }
    }

    $pwGiven = $false
    if ($Label -eq "Credential") {
        $pwGiven = [bool]$CredentialPasswordStdin
    }
    elseif ($Label -eq "WrongCredential") {
        $pwGiven = [bool]$WrongCredentialPasswordStdin
    }

    if ($Username -and -not $pwGiven) {
        throw "Invalid $Label source: -${Label}Username given without a password source. Use -${Label}PasswordStdin or -${Label} (PSCredential)."
    }
    if ($pwGiven -and -not $Username) {
        throw "Invalid $Label source: password-only given. Use -${Label}Username to name the account."
    }
    if (-not $Username -and -not $pwGiven) {
        return [ordered]@{ username = ""; password = $null; present = $false }
    }

    $password = Read-LineFromStdin
    return [ordered]@{
        username = $Username
        password = $password
        present  = $true
    }
}

$credentialState = Resolve-CredentialPair -Label "Credential" -Object $Credential -Username $CredentialUsername -FromStdin:$CredentialPasswordStdin
$wrongState = Resolve-CredentialPair -Label "WrongCredential" -Object $WrongCredential -Username $WrongCredentialUsername -FromStdin:$WrongCredentialPasswordStdin

$hasCredential = [bool]$credentialState.present
$hasWrongCredential = [bool]$wrongState.present

# Fail-closed parameter matrix. Each AuthMode accepts only its own credential
# surface; cross-mode or conflicting flags are rejected. Partial credential
# surfaces (username without a password source, or a password source without a
# username) have already been rejected above.
$conflicts = @()
if ($AuthMode -eq "None" -and ($AccessCookie -or $hasCredential -or $hasWrongCredential -or $ExpectAccessEnforcement)) {
    $conflicts += "AuthMode=None rejects all credential/access flags"
}
if ($AuthMode -eq "CaddyBasic" -and $ExpectAccessEnforcement) {
    $conflicts += "ExpectAccessEnforcement is Access-only; cannot combine with CaddyBasic"
}
if ($AuthMode -eq "CaddyBasic" -and $AccessCookie) {
    $conflicts += "AccessCookie is Access-only; cannot combine with CaddyBasic"
}
if ($AuthMode -eq "Access" -and ($hasCredential -or $hasWrongCredential)) {
    $conflicts += "Credential/WrongCredential are CaddyBasic-only; cannot combine with Access"
}
if ($AuthMode -eq "Access" -and $ExpectAccessEnforcement -and $AccessCookie) {
    $conflicts += "ExpectAccessEnforcement expects no AccessCookie (unauthenticated proof)"
}
if ($AuthMode -eq "Access" -and $EchoRoute) {
    $conflicts += "EchoRoute is CaddyBasic-only (header-strip observation)"
}
if ($AuthMode -eq "None" -and $EchoRoute) {
    $conflicts += "EchoRoute is CaddyBasic-only (header-strip observation)"
}
if ($conflicts.Count -gt 0) {
    throw "Invalid probe flag combination: $($conflicts -join '; ')"
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
        [string]$Username = "",
        [string]$Password = ""
    )

    $started = Get-Date
    $statusCode = $null
    $ok = $false
    $redirected = $false
    $err = $null
    $location = $null
    $wwwAuthenticate = $null
    $echoBody = $null

    $uri = New-Object System.Uri "$base$Route"
    $req = [System.Net.HttpWebRequest]::Create($uri)
    $req.Method = "GET"
    $req.AllowAutoRedirect = $false
    $req.Timeout = ($TimeoutSeconds * 1000)
    try { $req.Proxy = $null } catch { }
    try { $req.Credentials = $null } catch { }
    if ($Cookie) {
        try { $req.Headers.Add("Cookie", "CF_Authorization=$Cookie") } catch { }
    }
    if ($Username) {
        $pair = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${Username}:${Password}"))
        $req.Headers["Authorization"] = "Basic $pair"
    }

    $resp = $null
    try {
        $resp = $req.GetResponse()
    }
    catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        $err = $_.Exception.GetType().Name
    }
    catch {
        $err = $_.Exception.GetType().Name
        $resp = $null
    }

    if ($null -ne $resp) {
        try { $statusCode = [int]$resp.StatusCode } catch { $statusCode = $null }
        try { $location = [string]$resp.Headers["Location"] } catch { $location = $null }
        try { $wwwAuthenticate = [string]$resp.Headers["WWW-Authenticate"] } catch { $wwwAuthenticate = $null }

        if ($Route -eq $EchoRoute) {
            try {
                $stream = $resp.GetResponseStream()
                if ($null -ne $stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $echoBody = $reader.ReadToEnd()
                    $reader.Close()
                }
            }
            catch { $echoBody = $null }
        }

        $ok = ($statusCode -ge 200 -and $statusCode -lt 300)
        try { $resp.Close() } catch { }
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
        echo_body = $echoBody
    }
}

$service = $null
$serviceStatus = "unsupported"
if ($PSVersionTable.PSVersion.Major -ge 6 -and [OperatingSystem]::IsLinux()) {
    # Linux / pwsh has no Get-Service (no Windows SCM). The tunnel service is
    # Windows-specific; on this platform we report 'unsupported' rather than fail.
    $serviceStatus = "n/a"
}
else {
    try {
        $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        $serviceStatus = if ($null -eq $service) { "missing" } else { $service.Status.ToString() }
    }
    catch {
        $serviceStatus = "unavailable"
    }
}
$publicHttps = $base.StartsWith("https://")

$unauthenticatedRoutes = @(
    foreach ($route in $requiredRoutes) {
        Invoke-AetherProbeRoute -Route $route
    }
)

if ($AuthMode -eq "CaddyBasic") {
    $unauthenticatedAllDenied = (
        @($unauthenticatedRoutes | Where-Object { -not $_.basic_challenge }).Count -eq 0
    )
}
else {
    $unauthenticatedAllDenied = (
        @($unauthenticatedRoutes | Where-Object { -not $_.access_protected }).Count -eq 0
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
elseif ($AuthMode -eq "CaddyBasic" -and $hasCredential) {
    $authenticatedRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Username $credentialState.username -Password $credentialState.password
        }
    )
}
$authenticatedAllOk = (
    $authenticatedRoutes.Count -gt 0 -and
    @($authenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
)

$invalidRoutes = @()
if ($AuthMode -eq "CaddyBasic" -and $hasWrongCredential) {
    $invalidRoutes = @(
        foreach ($route in $requiredRoutes) {
            Invoke-AetherProbeRoute -Route $route -Username $wrongState.username -Password $wrongState.password
        }
    )
}
$invalidCredentialsAllDenied = (
    $invalidRoutes.Count -gt 0 -and
    @($invalidRoutes | Where-Object { -not $_.basic_challenge }).Count -eq 0
)

# Header-strip observation derived from the echo upstream: send an
# authenticated (Basic) request through Caddy to the echo route. The echo
# upstream returns the set of headers IT actually received as JSON. If
# "authorization" is absent there, Caddy stripped it before forwarding. This is
# an observation of the upstream boundary, never an inspection of Caddy
# /config/.
$headerStripObserved = $false
$authorizationForwardedToUpstream = $null
if ($AuthMode -eq "CaddyBasic" -and $hasCredential -and $EchoRoute) {
    $echoProbe = Invoke-AetherProbeRoute -Route $EchoRoute -Username $credentialState.username -Password $credentialState.password
    if ($echoProbe.echo_body -and ($echoProbe.status_code -ge 200 -and $echoProbe.status_code -lt 300)) {
        try {
            $echoHeaders = ($echoProbe.echo_body | ConvertFrom-Json)
            $echoProps = @($echoHeaders.PSObject.Properties.Name | ForEach-Object { $_.ToString().ToLowerInvariant() })
            $authorizationForwardedToUpstream = ($echoProps -contains "authorization")
            $headerStripObserved = $true
        }
        catch {
            $headerStripObserved = $false
            $authorizationForwardedToUpstream = $null
        }
    }
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
        @($unauthenticatedRoutes | Where-Object { -not $_.ok }).Count -eq 0
    }
}

$headerStripOk = if ($AuthMode -eq "CaddyBasic") {
    $headerStripObserved -and -not $authorizationForwardedToUpstream
}
else {
    $true
}

$status = if (
    $requiredOk -and
    $publicHttps -and
    $serviceStatus -eq "Running" -and
    $headerStripOk
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
    header_strip_observed = $headerStripObserved
    authorization_forwarded_to_upstream = $authorizationForwardedToUpstream
    secret_values_exposed = $false
}

$json = $receipt | ConvertTo-Json -Depth 10 -Compress
$json | Set-Content -LiteralPath $latestPath -Encoding UTF8
Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8
$receipt | ConvertTo-Json -Depth 10