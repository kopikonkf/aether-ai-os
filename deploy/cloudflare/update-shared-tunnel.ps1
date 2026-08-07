[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$TunnelConfig = "C:\Users\aethers\.cloudflared\config.yml",
    [string]$CloudflaredPath = "",
    [string]$LocalOrigin = "http://localhost:8080",
    [string[]]$AetherHostnames = @("aethers.my.id", "www.aethers.my.id"),
    [string[]]$ProtectedHostnames = @("oc.aethers.my.id", "jarvis.aethers.my.id"),
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

if (-not (Test-Path -LiteralPath $TunnelConfig -PathType Leaf)) {
    throw "Tunnel config not found: $TunnelConfig"
}
if (-not $CloudflaredPath) {
    $CloudflaredPath = (Get-Command cloudflared.exe -ErrorAction Stop).Source
}

$original = Get-Content -LiteralPath $TunnelConfig -Raw
$lines = $original -split "`r?`n"

# ---- Parse existing hostname entries and their service scalar. ----
function Get-IngressEntries {
    param([string[]]$SourceLines)

    $entries = @()
    $inIngress = $false
    foreach ($line in $SourceLines) {
        if ($line.Trim() -eq "ingress:") { $inIngress = $true; continue }
        if (-not $inIngress) { continue }
        $m = [regex]::Match($line, '^\s*-\s+hostname:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{
                type = "hostname"
                hostname = $m.Groups[1].Value
                line = $line
            }
            continue
        }
        $m = [regex]::Match($line, '^\s*-\s+service:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{
                type = "service"
                service = $m.Groups[1].Value
                line = $line
            }
        }
    }
    return $entries
}

$entries = Get-IngressEntries -SourceLines $lines

# --- Preflight: protected hosts must be present; fallback must be unique. ----
$entryHosts = @($entries | Where-Object { $_.type -eq "hostname" } | ForEach-Object { $_.hostname })
$protectedMissing = @($ProtectedHostnames | Where-Object { $_ -notin $entryHosts })
if ($protectedMissing.Count -gt 0) {
    throw "Protected host(s) missing from shared tunnel config: $($protectedMissing -join ', ')"
}
$fallbackServices = @($entries | Where-Object { $_.type -eq "service" -and $_.service -eq "http_status:404" })
if ($fallbackServices.Count -ne 1) {
    throw "Expected exactly one http_status:404 fallback; found $($fallbackServices.Count)"
}

# --- Build candidate config: change ONLY the service scalar for Aether hosts. ----
$newLines = @()
$inIngress = $false
$replaced = 0
foreach ($line in $lines) {
    if ($line.Trim() -eq "ingress:") { $inIngress = $true; $newLines += $line; continue }
    if (-not $inIngress) { $newLines += $line; continue }

    $m = [regex]::Match($line, '^(\s*-\s+hostname:\s*)(\S+)(\s*)$')
    if ($m.Success -and ($AetherHostnames -contains $m.Groups[2].Value)) {
        $newLines += $line
        $replaced++
        continue
    }

    # Change the service scalar that follows an Aether hostname entry.
    $svc = [regex]::Match($line, '^(\s*service:\s*)(\S+)(\s*)$')
    if ($svc.Success -and $replaced -gt 0) {
        # Only rewrite service lines that belong to the Aether hostname we just
        # emitted (the immediately preceding non-blank line was its hostname).
        $prevNonEmpty = $newLines | Where-Object { $_.Trim() -ne "" } | Select-Object -Last 1
        $prevHost = [regex]::Match($prevNonEmpty, '^\s*-\s+hostname:\s*(\S+)')
        if ($prevHost.Success -and ($AetherHostnames -contains $prevHost.Groups[1].Value)) {
            $newLines += $svc.Groups[1].Value + $LocalOrigin + $svc.Groups[3].Value
            $replaced--
            continue
        }
    }
    $newLines += $line
}

if ($replaced -ne 0) {
    throw "Aether hostname entry without a service scalar (unbalanced): remaining=$replaced"
}

$candidate = $newLines -join "`r`n"

# --- Derived observations from the parsed entries. ----
function Assert-RoutePreservation {
    param([string]$Config)

    foreach ($protected in $ProtectedHostnames) {
        if ($Config -notmatch [regex]::Escape("hostname: $protected")) {
            throw "Protected host was lost: $protected"
        }
    }
    if (($Config -split "http_status:404").Count -ne 2) {
        throw "Fallback http_status:404 must appear exactly once"
    }
    foreach ($hostname in $AetherHostnames) {
        $count = ($Config -split [regex]::Escape("hostname: $hostname")).Count - 1
        if ($count -ne 1) {
            throw "Aether host '$hostname' must appear exactly once; found $count"
        }
    }
}

Assert-RoutePreservation -Config $candidate

$ingressDir = Join-Path $AetherHome "runtime\ingress"
New-Item -ItemType Directory -Force -Path $ingressDir | Out-Null
$receiptPath = Join-Path $ingressDir "shared-tunnel-receipt.json"

$receipt = [ordered]@{
    schema = "aether.shared-tunnel.v2"
    event = "cloudflare.shared_tunnel.updated"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    applied = [bool]$Apply
    aether_hostnames = $AetherHostnames
    aether_origin = $LocalOrigin
    protected_hostnames = $ProtectedHostnames
    protected_preserved = $true
    fallback_unique = $true
    aether_entries_unique = $true
    config_path = $TunnelConfig
    config_before_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_sha256 = $null
    config_after_sha256 = $null
    validate_before_apply = $false
    rollback_triggered = $false
    connector_count_after = $null
    connector_readiness = $null
}

if (-not $Apply) {
    $receipt.candidate_sha256 = (
        [System.BitConverter]::ToString(
            [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                [Text.Encoding]::UTF8.GetBytes($candidate)
            )
        ).Replace("-", "").ToLowerInvariant()
    )
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    $receipt | ConvertTo-Json -Depth 8
    return
}

# ---- Validate-before-apply: write candidate to a same-directory file, then
#      atomically replace the live config after validation passes. ----
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$candidatePath = "$TunnelConfig.candidate-$stamp"
$backupPath = "$TunnelConfig.bak-$stamp"
Set-Content -LiteralPath $candidatePath -Value $candidate -Encoding UTF8
$receipt.candidate_sha256 = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()

try {
    & $CloudflaredPath tunnel --config $candidatePath ingress validate 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared ingress validate failed on candidate (exit $LASTEXITCODE)"
    }
    $receipt.validate_before_apply = $true

    # Atomic replacement: copy current to backup, then move candidate into place.
    Copy-Item -LiteralPath $TunnelConfig -Destination $backupPath -Force
    Move-Item -LiteralPath $candidatePath -Destination $TunnelConfig -Force

    Assert-RoutePreservation -Config (Get-Content -LiteralPath $TunnelConfig -Raw)
    $receipt.config_after_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($Start) {
        # ---- Reconcile exactly ONE cloudflared connector. ----
        $beforePids = @(Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
        $svc = Get-Service -Name Cloudflared -ErrorAction SilentlyContinue
        if ($null -ne $svc) {
            Restart-Service -Name Cloudflared -Force -ErrorAction Stop
        }
        else {
            throw "Cloudflared SCM service missing; cannot reconcile a single connector."
        }
        Start-Sleep -Seconds 3

        $afterPids = @(Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
        $receipt.connector_count_after = $afterPids.Count
        if ($afterPids.Count -ne 1) {
            $receipt.rollback_triggered = $true
            throw "Expected exactly one cloudflared process; found $($afterPids.Count). Rolling back config."
        }

        # Tunnel-owned readiness: cloudflared metrics endpoint (not generic port 2019).
        $metricsOk = $false
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:20120/metrics" -TimeoutSec $ProbeTimeoutSeconds -UseBasicParsing
            $metricsOk = ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
        }
        catch {
            $metricsOk = $false
        }
        $receipt.connector_readiness = $metricsOk
        if (-not $metricsOk) {
            # Fail closed: restore backup, restart service, prove recovery.
            Copy-Item -LiteralPath $backupPath -Destination $TunnelConfig -Force
            $receipt.rollback_triggered = $true
            if ($null -ne $svc) {
                Restart-Service -Name Cloudflared -Force -ErrorAction SilentlyContinue
            }
            throw "cloudflared connector readiness (metrics) failed after apply; config restored to backup."
        }
    }
}
catch {
    if (Test-Path -LiteralPath $candidatePath) {
        Remove-Item -LiteralPath $candidatePath -Force -ErrorAction SilentlyContinue
    }
    $receipt.rollback_triggered = $true
    $receipt.error = $_.Exception.Message
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    throw
}

if (Test-Path -LiteralPath $candidatePath) {
    Remove-Item -LiteralPath $candidatePath -Force
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8