[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$PublicHostname = "",
    [string]$TunnelId = "",
    [string]$CredentialsFile = "",
    [string]$CloudflaredPath = "",
    [string]$LocalOrigin = "http://127.0.0.1:80",
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
$runtimeDir = Join-Path $AetherHome "runtime"
$ingressDir = Join-Path $runtimeDir "ingress"
New-Item -ItemType Directory -Force -Path $AetherHome, $cloudflareDir, $runtimeDir, $ingressDir | Out-Null
icacls $AetherHome /inheritance:e /grant "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null

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
    Start-Service -Name $serviceName
}

$manifest | ConvertTo-Json -Depth 8
