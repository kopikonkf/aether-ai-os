[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$TunnelConfig = "C:\Users\aethers\.cloudflared\config.yml",
    [string]$CloudflaredPath = "",
    [string]$LocalOrigin = "http://localhost:8080",
    [string[]]$AetherHostnames = @("aethers.my.id", "www.aethers.my.id"),
    [string[]]$ProtectedHosts = @("oc.aethers.my.id", "jarvis.aethers.my.id"),
    [int]$ProbeTimeoutSeconds = 8,
    [switch]$Apply,
    [switch]$Start
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this update from an elevated PowerShell session."
    }
}

Assert-Administrator

if (-not (Test-Path -LiteralPath $TunnelConfig -PathType Leaf)) {
    throw "Tunnel config not found: $TunnelConfig"
}

if (-not $CloudflaredPath) {
    $CloudflaredPath = (Get-Command cloudflared.exe -ErrorAction Stop).Source
}

# ---- Load + parse the current shared tunnel config (preserve everything). ----
$original = Get-Content -LiteralPath $TunnelConfig -Raw

function Parse-IngressService {
    param([string]$Line)

    $trimmed = $Line.Trim()
    if ($trimmed -notmatch '^- hostname:') {
        return $null
    }
    return $trimmed
}

$lines = $original -split "`r?`n"
$ingressBlockStart = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Trim() -eq "ingress:") {
        $ingressBlockStart = $i
        break
    }
}
if ($ingressBlockStart -lt 0) {
    throw "No 'ingress:' block found in $TunnelConfig"
}

# Collect every existing hostname entry so the rewrite can preserve them.
$knownHosts = @{}
$inIngress = $false
foreach ($line in $lines) {
    if ($line.Trim() -eq "ingress:") { $inIngress = $true; continue }
    if (-not $inIngress) { continue }
    if ($line -match '^\s*-\s+service:\s*http_status:404') { continue }
    $m = [regex]::Match($line, '^\s*-\s+hostname:\s*(\S+)')
    if ($m.Success) {
        $knownHosts[$m.Groups[1].Value] = $true
    }
}

$protectedMissing = @($ProtectedHosts | Where-Object { -not $knownHosts.ContainsKey($_) })
if ($protectedMissing.Count -gt 0) {
    throw "Protected host(s) missing from shared tunnel config: $($protectedMissing -join ', ')"
}

# ---- Build the new config: change ONLY the Aether host origins to $LocalOrigin. ----
$newLines = @()
$inIngress = $false
foreach ($line in $lines) {
    if ($line.Trim() -eq "ingress:") {
        $inIngress = $true
        $newLines += $line
        continue
    }
    if (-not $inIngress) {
        $newLines += $line
        continue
    }
    $hostEntry = [regex]::Match($line, '^(\s*-\s+hostname:\s*)(\S+)(\s*)$')
    if ($hostEntry.Success -and ($AetherHostnames -contains $hostEntry.Groups[2].Value)) {
        $indent = '    '
        $newLines += "$indent- hostname: $($hostEntry.Groups[2].Value)"
        $newLines += "$indent  service: $LocalOrigin"
        $newLines += "$indent  originRequest:"
        $newLines += "$indent    connectTimeout: 10s"
        $newLines += "$indent    noTLSVerify: true"
        continue
    }
    $newLines += $line
}

$newConfig = $newLines -join "`r`n"

# ---- Preflight assertions (no mutation without -Apply). ----
function Assert-RoutePreservation {
    param([string]$Config)

    foreach ($hostEntry in $ProtectedHosts) {
        if ($Config -notmatch [regex]::Escape($hostEntry)) {
            throw "Protected host was lost: $hostEntry"
        }
    }
    if ($Config -notmatch 'http_status:404') {
        throw "Fallback http_status:404 was lost"
    }
}

Assert-RoutePreservation -Config $newConfig

$beforeSha = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

$dryRun = [ordered]@{
    schema = "aether.shared-tunnel.v1"
    event = "cloudflare.shared_tunnel.updated"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    applied = [bool]$Apply
    aether_hosts = $AetherHostnames
    aether_origin = $LocalOrigin
    protected_hosts = $ProtectedHosts
    protected_preserved = $true
    fallback_preserved = $true
    config_path = $TunnelConfig
    config_before_sha256 = $beforeSha
    config_after_sha256 = $null
    rollback_triggered = $false
}

if (-not $Apply) {
    $dryRun.config_after_sha256 = (
        [System.BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($newConfig)
            )
        ).Replace("-", "").ToLowerInvariant()
    )
    $dryRun | ConvertTo-Json -Depth 8
    return
}

# ---- Apply with backup + validate + rollback. ----
$backupPath = "$TunnelConfig.bak-$(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')"
Copy-Item -LiteralPath $TunnelConfig -Destination $backupPath -Force

try {
    Set-Content -LiteralPath $TunnelConfig -Value $newConfig -Encoding UTF8
    Assert-RoutePreservation -Config $newConfig
    & $CloudflaredPath tunnel --config $TunnelConfig ingress validate 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared ingress validate failed"
    }

    $dryRun.config_after_sha256 = (
        Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    if ($Start) {
        # Restart the SCM-managed cloudflared connector (single connector policy).
        $svc = Get-Service -Name Cloudflared -ErrorAction SilentlyContinue
        if ($null -ne $svc) {
            Restart-Service -Name Cloudflared -Force -ErrorAction Stop
        }
        Start-Sleep -Seconds 2
        try {
            $health = Invoke-WebRequest -Uri "http://127.0.0.1:2019/health" -TimeoutSec $ProbeTimeoutSeconds -UseBasicParsing
            if ($health.StatusCode -ne 200) {
                throw "tunnel health probe failed (status $($health.StatusCode))"
            }
        }
        catch {
            # Roll back config on probe failure.
            Copy-Item -LiteralPath $backupPath -Destination $TunnelConfig -Force
            $dryRun.rollback_triggered = $true
            throw "Tunnel health probe failed after apply; config rolled back. Error: $($_.Exception.Message)"
        }
    }
}
catch {
    if (Test-Path -LiteralPath $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $TunnelConfig -Force
    }
    throw
}

$ingressDir = Join-Path $AetherHome "runtime\ingress"
New-Item -ItemType Directory -Force -Path $ingressDir | Out-Null
$dryRun | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ingressDir "shared-tunnel-receipt.json") -Encoding UTF8
$dryRun | ConvertTo-Json -Depth 8