[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$PublicHostname = "",
    [string]$TunnelId = "",
    [string]$CredentialsFile = "",
    [string]$CloudflaredPath = "",
    [string]$CaddyPath = "C:\Program Files\Caddy\caddy.exe",
    [string]$CaddyfileSource = "",
    [string]$LocalOrigin = "http://127.0.0.1:8080",
    [string]$FounderUsername = "founder",
    [string]$FounderAuthFile = "",
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this installer from an elevated PowerShell session."
    }
}

function Quote-Arg {
    param([Parameter(Mandatory = $true)][string]$Value)
    return '"' + $Value + '"'
}

function Join-ServiceCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $items = @((Quote-Arg $Executable))
    foreach ($argument in $Arguments) {
        $items += (Quote-Arg $argument)
    }
    return ($items -join ' ')
}

Assert-Administrator

if (-not $PublicHostname) {
    throw "PublicHostname is required."
}
if (-not $TunnelId) {
    throw "TunnelId is required."
}
if (-not $CredentialsFile) {
    throw "CredentialsFile is required."
}
if (-not (Test-Path -LiteralPath $CredentialsFile -PathType Leaf)) {
    throw "Missing Cloudflare credentials file: $CredentialsFile"
}
if (-not $CloudflaredPath) {
    $CloudflaredPath = (Get-Command cloudflared.exe -ErrorAction Stop).Source
}

$cloudflareDir = Join-Path $AetherHome "cloudflare"
$caddyDir = Join-Path $AetherHome "caddy"
$runtimeDir = Join-Path $AetherHome "runtime"
$ingressDir = Join-Path $runtimeDir "ingress"

$homeExistedBefore = Test-Path -LiteralPath $AetherHome -PathType Container

New-Item -ItemType Directory -Force -Path $AetherHome, $cloudflareDir, $caddyDir, $runtimeDir, $ingressDir | Out-Null

if (-not $homeExistedBefore) {
    & icacls $AetherHome /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "ACL hardening failed for AETHER_HOME with exit code $LASTEXITCODE"
    }
}

function Assert-AetherHomeProtected {
    $homeAcl = Get-Acl -LiteralPath $AetherHome
    $requiredRules = @{
        "S-1-5-18" = $false
        "S-1-5-32-544" = $false
    }
    $aclViolations = @()
    if (-not $homeAcl.AreAccessRulesProtected) {
        $aclViolations += "inheritance_not_disabled"
    }
    $hasContainerInherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit
    $hasObjectInherit = [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    foreach ($rule in $homeAcl.Access) {
        try {
            $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        }
        catch {
            $sid = [string]$rule.IdentityReference
        }
        if ($sid -notin @($requiredRules.Keys)) {
            $aclViolations += "unexpected_rule:${sid}:$($rule.AccessControlType)"
            continue
        }
        $ruleIsFullControlAllow = (
            $rule.AccessControlType -eq "Allow" -and
            ($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq [System.Security.AccessControl.FileSystemRights]::FullControl
        )
        $inherits = ([bool]($rule.InheritanceFlags -band $hasContainerInherit) -and [bool]($rule.InheritanceFlags -band $hasObjectInherit))
        if (-not ($ruleIsFullControlAllow -and $inherits)) {
            $aclViolations += "required_rule_incomplete:${sid}:rights=$($rule.FileSystemRights):inherit=$($rule.InheritanceFlags)"
        }
        else {
            $requiredRules[$sid] = $true
        }
    }
    foreach ($sid in @($requiredRules.Keys)) {
        if (-not $requiredRules[$sid]) {
            $aclViolations += "required_sid_missing:${sid}"
        }
    }
    if ($aclViolations.Count -gt 0) {
        throw "ACL postcondition verification failed for AETHER_HOME: $($aclViolations -join ', ')"
    }
}

if (-not (Test-Path -LiteralPath $CaddyPath -PathType Leaf)) {
    throw "Caddy binary not found: $CaddyPath (download v2.11.3 Windows AMD64 or pass -CaddyPath)"
}

$caddyfilePath = Join-Path $caddyDir "Caddyfile"
if (-not $CaddyfileSource) {
    $CaddyfileSource = Join-Path $PSScriptRoot "..\windows\Caddyfile"
}
if (-not (Test-Path -LiteralPath $CaddyfileSource -PathType Leaf)) {
    throw "Caddyfile source not found: $CaddyfileSource"
}
Copy-Item -LiteralPath $CaddyfileSource -Destination $caddyfilePath -Force

$authFragmentPath = Join-Path $caddyDir "founder-auth.caddy"

if ($FounderUsername -notmatch '^[a-zA-Z0-9_-]{1,64}$') {
    throw "Founder username must be a safe fixed identifier: $FounderUsername"
}

if ($FounderAuthFile) {
    if (-not (Test-Path -LiteralPath $FounderAuthFile -PathType Leaf)) {
        throw "Founder auth hash file not found: $FounderAuthFile"
    }
    $authHashValue = (Get-Content -LiteralPath $FounderAuthFile -Raw).Trim()
    if ($authHashValue -match " " -or $authHashValue -match "`t") {
        throw "Founder auth file must contain only a single bcrypt hash"
    }
    if ($authHashValue -notmatch '^[$]2[aby]\$14\$[./A-Za-z0-9]{53}$') {
        throw "Founder auth hash is not a valid cost-14 bcrypt hash"
    }

    $authFragment = @"
basic_auth bcrypt "Aether Founder Alpha" {
    $FounderUsername $authHashValue
}
"@
    $authFragment | Set-Content -LiteralPath $authFragmentPath -Encoding UTF8
}
elseif (-not (Test-Path -LiteralPath $authFragmentPath -PathType Leaf)) {
    throw "Founder auth fragment missing and -FounderAuthFile not provided: $authFragmentPath"
}

& icacls $authFragmentPath /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "ACL hardening failed for $authFragmentPath"
}
$fragAcl = Get-Acl -LiteralPath $authFragmentPath
$fragViolations = @()
if (-not $fragAcl.AreAccessRulesProtected) {
    $fragViolations += "inheritance_not_disabled"
}
foreach ($rule in $fragAcl.Access) {
    try {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        $sid = [string]$rule.IdentityReference
    }
    if ($sid -notin @("S-1-5-18", "S-1-5-32-544") -or $rule.AccessControlType -ne "Allow") {
        $fragViolations += "unexpected_rule:${sid}:$($rule.AccessControlType)"
    }
}
if ($fragViolations.Count -gt 0) {
    throw "ACL postcondition failed for ${authFragmentPath}: $($fragViolations -join ', ')"
}

# The auth fragment is secret-bearing. Fail closed unless the (possibly
# pre-existing) AETHER_HOME root is itself protected SYSTEM/Administrators.
Assert-AetherHomeProtected

& $CaddyPath validate --config $caddyfilePath --adapter caddyfile | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Caddy configuration validation failed for $caddyfilePath"
}

$caddyServiceName = "AetherCaddy"
$caddyBinaryPath = '"' + $CaddyPath + '" run --config "' + $caddyfilePath + '" --adapter caddyfile'
$existingCaddy = Get-Service -Name $caddyServiceName -ErrorAction SilentlyContinue
if ($null -eq $existingCaddy) {
    New-Service -Name $caddyServiceName -DisplayName "Aether Caddy Router" -Description "Aether Caddy one-domain router (:8080) for Cloudflare ingress." -BinaryPathName $caddyBinaryPath -StartupType Automatic | Out-Null
}
else {
    sc.exe config $caddyServiceName binPath= "$caddyBinaryPath" start= auto | Out-Null
    Set-Service -Name $caddyServiceName -StartupType Automatic
}
sc.exe failure $caddyServiceName reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null

$configPath = Join-Path $cloudflareDir "config.yml"
$manifestPath = Join-Path $cloudflareDir "cloudflare-ingress-manifest.json"

@"
tunnel: $TunnelId
credentials-file: $CredentialsFile

ingress:
  - hostname: $PublicHostname
    service: $LocalOrigin
    originRequest:
      connectTimeout: 10s
      noTLSVerify: true
  - service: http_status:404
"@ | Set-Content -LiteralPath $configPath -Encoding UTF8

$serviceName = "AetherCloudflareTunnel"
$serviceArgs = @("tunnel", "--config", $configPath, "run")
$binaryPath = Join-ServiceCommand $CloudflaredPath $serviceArgs
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    New-Service -Name $serviceName -DisplayName "Aether Cloudflare Tunnel" -Description "Cloudflare Tunnel ingress for Aether one-domain host." -BinaryPathName $binaryPath -StartupType Automatic | Out-Null
}
else {
    sc.exe config $serviceName binPath= "$binaryPath" start= auto | Out-Null
    Set-Service -Name $serviceName -StartupType Automatic
}
sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null

$manifest = [ordered]@{
    schema = "aether.cloudflare-ingress.v1"
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
    public_hostname = $PublicHostname
    tunnel_id_sha256 = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($TunnelId))).ToLowerInvariant()
    caddy_service = $caddyServiceName
    caddy_path = $CaddyPath
    caddyfile_path = $caddyfilePath
    auth_mode = "caddy_basic_bcrypt"
    auth_scope = "all_paths"
    auth_fragment = (if (Test-Path -LiteralPath $authFragmentPath) { "founder-auth.caddy" } else { $null })
    auth_hash_recorded = $false
    service_name = $serviceName
    local_origin = $LocalOrigin
    config_path = $configPath
    credentials_file_path = $CredentialsFile
    latest_probe_path = (Join-Path $ingressDir "latest_cloudflare_probe.json")
    probe_log_path = (Join-Path $ingressDir "cloudflare-probes.jsonl")
    required_routes = @("/health", "/aether/api/status", "/api/browser-senses/status", "/senses")
    secret_values_exposed = $false
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

if ($Start) {
    Start-Service -Name $caddyServiceName
    Start-Service -Name $serviceName
}

$manifest | ConvertTo-Json -Depth 8
