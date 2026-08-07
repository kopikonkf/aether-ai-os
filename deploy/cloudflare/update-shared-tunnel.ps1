[CmdletBinding()]
param(
    [string]$AetherHome = "C:\ProgramData\Aether",
    [string]$TunnelConfig = "C:\Users\aethers\.cloudflared\config.yml",
    [string]$CloudflaredPath = "",
    [string]$LocalOrigin = "http://localhost:8080",
    [string[]]$AetherHostnames = @("aethers.my.id", "www.aethers.my.id"),
    [string[]]$ProtectedHostnames = @("oc.aethers.my.id", "jarvis.aethers.my.id"),
    [string]$ConnectorServiceName = "Cloudflared",
    [int]$ConnectorMetricsPort = 20120,
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

function Get-IngressEntries {
    param([string[]]$SourceLines)

    $entries = @()
    $inIngress = $false
    foreach ($line in $SourceLines) {
        if ($line.Trim() -eq "ingress:") { $inIngress = $true; continue }
        if (-not $inIngress) { continue }
        $m = [regex]::Match($line, '^\s*-\s+hostname:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{ type = "hostname"; hostname = $m.Groups[1].Value; line = $line }
            continue
        }
        $m = [regex]::Match($line, '^\s*-\s+service:\s*(\S+)\s*$')
        if ($m.Success) {
            $entries += [ordered]@{ type = "service"; service = $m.Groups[1].Value; line = $line }
        }
    }
    return $entries
}

$entries = Get-IngressEntries -SourceLines $lines

$entryHosts = @($entries | Where-Object { $_.type -eq "hostname" } | ForEach-Object { $_.hostname })
$protectedMissing = @($ProtectedHostnames | Where-Object { $_ -notin $entryHosts })
if ($protectedMissing.Count -gt 0) {
    throw "Protected host(s) missing from shared tunnel config: $($protectedMissing -join ', ')"
}
$fallbackServices = @($entries | Where-Object { $_.type -eq "service" -and $_.service -eq "http_status:404" })
if ($fallbackServices.Count -ne 1) {
    throw "Expected exactly one http_status:404 fallback; found $($fallbackServices.Count)"
}

# --- Build candidate config: change ONLY the service scalar for Aether hosts. ---
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

    $svc = [regex]::Match($line, '^(\s*service:\s*)(\S+)(\s*)$')
    if ($svc.Success -and $replaced -gt 0) {
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
    schema = "aether.shared-tunnel.v3"
    event = "cloudflare.shared_tunnel.updated"
    observed_at = (Get-Date).ToUniversalTime().ToString("o")
    applied = [bool]$Apply
    started = [bool]$Start
    aether_hostnames = $AetherHostnames
    aether_origin = $LocalOrigin
    protected_hostnames = $ProtectedHostnames
    connector_service = $ConnectorServiceName
    connector_metrics_port = $ConnectorMetricsPort
    config_path = $TunnelConfig
    config_before_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_sha256 = $null
    config_after_sha256 = $null
    validate_before_apply = $false
    live_config_replaced = $false
    rollback_triggered = $false
    recovery_proven = $null
    connector_count_before = $null
    connector_count_after = $null
    connector_readiness = $null
}

# ---- Helpers for connector handoff / recovery (only meaningful with -Start). ----
function Stop-AllCloudflaredProcesses {
    foreach ($p in @(Get-Process cloudflared -ErrorAction SilentlyContinue)) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Seconds 2
}

function Get-ScmConnectorInfo {
    # Returns the SCM connector process info if it matches our tunnel config
    $svc = Get-Service -Name $ConnectorServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) { return $null }
    
    $pids = @(Get-Process cloudflared -ErrorAction SilentlyContinue | Where-Object { $_.Id -eq $svc.Id })
    if ($pids.Count -ne 1) { return $null }
    
    $proc = $pids[0]
    $cmdline = $proc.CommandLine
    $matchesConfig = $cmdline -match [regex]::Escape($TunnelConfig)
    $matchesTunnel = $cmdline -match '8f53133'
    $matchesMetrics = $cmdline -match [regex]::Escape("--metrics $ConnectorMetricsPort") -or $cmdline -match [regex]::Escape("--metrics=127.0.0.1:$ConnectorMetricsPort")
    
    return [ordered]@{
        pid = $proc.Id
        cmdline = $cmdline
        matchesConfig = $matchesConfig
        matchesTunnel = $matchesTunnel
        matchesMetrics = $matchesMetrics
        isValid = $matchesConfig -and $matchesTunnel -and $matchesMetrics
    }
}

function Stop-AllCloudflaredProcesses {
    foreach ($p in @(Get-Process cloudflared -ErrorAction SilentlyContinue)) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } catch { }
    }
    Start-Sleep -Seconds 2
}

function Restart-ScmConnector {
    $svc = Get-Service -Name $ConnectorServiceName -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        throw "Connector SCM service '$ConnectorServiceName' missing."
    }
    # Governed handoff: stop every cloudflared process (direct PID or leftover),
    # then start the single SCM connector.
    Stop-AllCloudflaredProcesses
    if ($svc.Status -eq "Stopped") {
        Start-Service -Name $ConnectorServiceName -ErrorAction Stop
    }
    else {
        Restart-Service -Name $ConnectorServiceName -Force -ErrorAction Stop
    }
    Start-Sleep -Seconds 3
    return Get-ScmConnectorInfo
}

function Assert-SingleConnector {
    $info = Get-ScmConnectorInfo
    $pids = @(Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
    $receipt.connector_count_after = $pids.Count
    if ($pids.Count -ne 1) {
        throw "Expected exactly one cloudflared process; found $($pids.Count) ($($pids -join ','))"
    }
    if (-not $info.isValid) {
        throw "SCM connector does not match expected config/tunnel/metrics. PID: $($info.pid), cmdline: $($info.cmdline)"
    }
    $receipt.connector_count_after = 1
    $receipt.connector_pid = $info.pid
    $receipt.connector_cmdline = $info.cmdline
    $receipt.connector_bound = $true
    return $true
}

function Test-ConnectorReadiness {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$ConnectorMetricsPort/metrics" -TimeoutSec $ProbeTimeoutSeconds -UseBasicParsing
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 300)
    }
    catch {
        return $false
    }
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

# ---- Validate-before-apply + atomic replace. ----
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$candidatePath = "$TunnelConfig.candidate-$stamp"
$backupPath = "$TunnelConfig.bak-$stamp"
Set-Content -LiteralPath $candidatePath -Value $candidate -Encoding UTF8
$receipt.candidate_sha256 = (Get-FileHash -LiteralPath $candidatePath -Algorithm SHA256).Hash.ToLowerInvariant()

$connectorService = $null
$restoreFailed = $false

function Restore-SharedTunnelState {
    # Restore the live config to its backup and reconcile the connector back to
    # the previous state. Never claims recovery unless it is observed.
    if (Test-Path -LiteralPath $backupPath) {
        Copy-Item -LiteralPath $backupPath -Destination $TunnelConfig -Force
    }
    $receipt.config_after_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

    $recovered = $false
    if ($receipt.connector_mutation_started) {
        try {
            Stop-AllCloudflaredProcesses
            if ((Get-Service -Name $ConnectorServiceName -ErrorAction SilentlyContinue).Status -eq "Stopped") {
                Start-Service -Name $ConnectorServiceName -ErrorAction Stop
            }
            else {
                Restart-Service -Name $ConnectorServiceName -Force -ErrorAction Stop
            }
            Start-Sleep -Seconds 3
            $info = Get-ScmConnectorInfo
            if ($null -ne $info -and $info.isValid) {
                $recovered = (Test-ConnectorReadiness)
            }
        }
        catch {
            $recovered = $false
        }
    }
    else {
        $recovered = $true  # no connector mutation was performed -> config restore is sufficient
    }
    $receipt.recovery_proven = $recovered
    return $recovered
}

try {
    & $CloudflaredPath tunnel --config $candidatePath ingress validate 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared ingress validate failed on candidate (exit $LASTEXITCODE)"
    }
    $receipt.validate_before_apply = $true

    Copy-Item -LiteralPath $TunnelConfig -Destination $backupPath -Force
    Move-Item -LiteralPath $candidatePath -Destination $TunnelConfig -Force
    $receipt.live_config_replaced = $true

    Assert-RoutePreservation -Config (Get-Content -LiteralPath $TunnelConfig -Raw)
    $receipt.config_after_sha256 = (Get-FileHash -LiteralPath $TunnelConfig -Algorithm SHA256).Hash.ToLowerInvariant()

    if ($Start) {
        $beforePids = @(Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id)
        $receipt.connector_count_before = $beforePids.Count
        $receipt.connector_mutation_started = $true
        
        # Stop ALL cloudflared processes (direct PID + any SCM) BEFORE starting SCM connector
        Stop-AllCloudflaredProcesses
        
        $connectorService = Restart-ScmConnector
        Assert-SingleConnector
        $metricsOk = Test-ConnectorReadiness
        $receipt.connector_readiness = $metricsOk
        if (-not $metricsOk) {
            throw "cloudflared connector readiness (metrics) failed after apply."
        }
    }
}
catch {
    $receipt.rollback_triggered = $true
    $receipt.error = $_.Exception.Message
    if ($receipt.live_config_replaced) {
        $receipt.recovery_proven = (Restore-SharedTunnelState)
    }
    if (Test-Path -LiteralPath $candidatePath) {
        Remove-Item -LiteralPath $candidatePath -Force -ErrorAction SilentlyContinue
    }
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    throw
}

if (Test-Path -LiteralPath $candidatePath) {
    Remove-Item -LiteralPath $candidatePath -Force
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 8